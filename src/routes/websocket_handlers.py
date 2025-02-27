from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Optional
import logging
import json
from datetime import datetime
import asyncio
from database.config import get_db
from managers.connection_manager import ConnectionManager
from utils.logger import setup_logging
from config.settings import settings
from database.models import Company, Agent

router = APIRouter()
setup_logging()
logger = logging.getLogger(__name__)

manager: Optional[ConnectionManager] = None


async def get_company_and_agent(api_key: str, agent_id: str, db: Session) -> Optional[dict]:
    """Validate company API key and agent, return both if valid"""
    try:
        logger.info(f"Validating company with API key: {api_key}")
        company = db.query(Company).filter_by(api_key=api_key).first()
        if not company:
            logger.warning(f"Company not found for API key: {api_key}")
            return None
        
        logger.info(f"Found company: {company.id}. Validating agent: {agent_id}")
        agent = db.query(Agent).filter_by(
            id=agent_id,
            company_id=company.id,
            active=True
        ).first()
        
        if not agent:
            logger.warning(f"Agent not found or inactive: {agent_id}")
            return None
            
        logger.info(f"Validation successful for company {company.id} and agent {agent.id}")
        return {
            "company": {
                "id": company.id,
                "name": company.name,
                "settings": company.settings
            },
            "agent": {
                "id": agent.id,
                "name": agent.name,
                "type": agent.type,
                "prompt": agent.prompt,
                "confidence_threshold": agent.confidence_threshold
            }
        }
    except Exception as e:
        logger.error(f"Database error in validation: {str(e)}")
        return None


@router.websocket("/{client_id}/{company_api_key}/{agent_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    client_id: str,
    company_api_key: str,
    agent_id: str,
    db: Session = Depends(get_db)
):
    global manager
    if not manager:
        manager = websocket.app.state.connection_manager
    
    logger.info(f"Connection attempt - Client ID: {client_id}, API Key: {company_api_key}, Agent ID: {agent_id}")
    
    try:
        # Validate company and agent
        validation_result = await get_company_and_agent(company_api_key, agent_id, db)
        if not validation_result:
            logger.warning("Validation failed")
            if not websocket.client_state.name == "DISCONNECTED":
                await websocket.close(code=4001)
            return

        # Accept connection first
        await websocket.accept()
        logger.info("Validation successful, accepting connection")
        
        # Initialize connection in manager
        logger.info("Initializing connection in manager")
        await manager.connect(websocket, client_id)

        # Set company and agent info
        logger.info("Setting company and agent info")
        manager.client_companies[client_id] = validation_result["company"]
        manager.active_agents[client_id] = agent_id

        # Send initial acknowledgment
        try:
            await websocket.send_json({
                "type": "status",
                "status": "initializing"
            })
        except Exception as e:
            logger.error(f"Error sending init status: {str(e)}")
            return

        # Initialize client resources
        logger.info("Initializing client resources")
        success = await manager.initialize_agent_resources(
            client_id,
            validation_result["company"]["id"],
            validation_result["agent"]
        )
        
        if not success:
            logger.error("Failed to initialize agent resources")
            if not websocket.client_state.name == "DISCONNECTED":
                await websocket.close(code=4002)
            return

        logger.info("Connection setup complete")
        
        # Send ready status using direct websocket send
        if not websocket.client_state.name == "DISCONNECTED":
            try:
                await websocket.send_json({
                    "type": "status",
                    "status": "ready",
                    "metadata": {
                        "agent_id": agent_id,
                        "timestamp": datetime.utcnow().isoformat()
                    }
                })
                logger.info("Sent ready status")
            except Exception as e:
                logger.error(f"Error sending ready status: {str(e)}")
                return

        # Message loop
        while not websocket.client_state.name == "DISCONNECTED":
            try:
                data = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=settings.WS_HEARTBEAT_INTERVAL
                )
                
                if not data:
                    continue
                    
                message_data = json.loads(data)
                message_type = message_data.get('type', '')
                
                if message_type == 'ping':
                    if not websocket.client_state.name == "DISCONNECTED":
                        await websocket.send_json({"type": "pong"})
                elif message_type == 'message':
                    await manager.process_streaming_message(client_id, message_data)
                
            except asyncio.TimeoutError:
                # Send heartbeat
                if not websocket.client_state.name == "DISCONNECTED":
                    try:
                        await websocket.send_json({"type": "ping"})
                    except Exception as e:
                        logger.error(f"Error sending heartbeat: {str(e)}")
                        break
            except WebSocketDisconnect:
                logger.info(f"WebSocket disconnected for client {client_id}")
                break
            except json.JSONDecodeError:
                logger.error("Invalid JSON received")
                continue
            except Exception as e:
                logger.error(f"Error in message loop: {str(e)}")
                break

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for client {client_id}")
    except Exception as e:
        logger.error(f"Unexpected error in websocket endpoint: {str(e)}")
    finally:
        # Cleanup without trying to close websocket again
        logger.info(f"Cleaning up connection for client {client_id}")
        if client_id in manager.active_connections:
            try:
                await manager.cleanup_agent_resources(client_id)
                manager.disconnect(client_id)
            except Exception as e:
                logger.error(f"Error during cleanup: {str(e)}")