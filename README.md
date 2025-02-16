# Callsure AI Backend

Date: 01/02/2025


# AI Backend

## Overview

This project is a backend system for AI-driven services, including GPT, RAG (Retrieval-Augmented Generation), TTS (Text-to-Speech), and STT (Speech-to-Text) capabilities. The backend integrates with AWS Aurora for database management, S3 for file storage, and various AI APIs to create a scalable and efficient infrastructure.

---

## **Directory Structure**

### **1. `docs/`**
**Purpose**: Centralized documentation for the project, accessible to both developers and DevOps teams.

- **`api.md`**:
  - Detailed descriptions of API endpoints, including:
    - Endpoint URLs, HTTP methods, query parameters, and request/response schemas.
    - Example cURL commands for testing APIs.
  - Includes documentation generated by FastAPI’s built-in OpenAPI schema.

- **`architecture.md`**:
  - High-level overview of the backend’s architecture:
    - System flow for GPT, RAG, TTS/STT.
    - Integration with AWS Aurora, S3, and EC2.
    - Deployment pipelines and scaling strategies.

- **`setup.md`**:
  - Step-by-step instructions for local development, including:
    - Environment setup (Python version, dependencies, etc.).
    - Configuring AWS resources like S3 buckets and RDS instances.
    - Running the backend server locally.

---

### **2. `scripts/`**
**Purpose**: Utility shell scripts for deployment and maintenance tasks.

- **`start.sh`**:
  - Starts the FastAPI server with Uvicorn.
  - Example:
    ```bash
    #!/bin/bash
    uvicorn src.main:app --host 0.0.0.0 --port 8000
    ```

- **`deploy.sh`**:
  - Automates deployment to an AWS EC2 instance or container.
  - Example steps:
    1. Build Docker image.
    2. Push to Amazon ECR (Elastic Container Registry).
    3. Deploy on ECS or EC2.

- **`cleanup.sh`**:
  - Cleans temporary files (logs, Docker volumes) after deployment.

---

### **3. `src/`**

#### **`src/api/`**
**Purpose**: Interfaces with external APIs like GPT, Claude, Llama, TTS, and STT.

- **Structure**:
  - **`service.py`**: Main logic to interact with the external API.
  - **`utils.py`**: Helper functions (e.g., payload creation, retry logic).
  - **`tts/` and `stt/`**:
    - Contains separate files for each TTS/STT provider.
    - Examples:
      - `eleven_labs.py`: Wrapper for Eleven Labs API.
      - `deepgram.py`: Wrapper for Deepgram API.

#### **`src/config/`**
**Purpose**: Centralized configuration management.

- **`settings.py`**:
  - Application-wide settings like:
    ```python
    DEBUG = True
    DATABASE_URL = "postgresql+asyncpg://user:password@host/dbname"
    ```

- **`aws_config.py`**:
  - AWS-specific configurations:
    ```python
    S3_BUCKET_NAME = "your-s3-bucket"
    S3_REGION = "us-east-1"
    ```

#### **`src/controllers/`**
**Purpose**: Orchestrates workflows across APIs and services.

- **`ai_controller.py`**:
  - Combines GPT with RAG for a conversational query pipeline.

- **`voice_controller.py`**:
  - Manages TTS and STT tasks, converting audio to text and vice versa.

#### **`src/middleware/`**
**Purpose**: Handles pre- and post-processing of API requests.

- **`auth_middleware.py`**: Ensures endpoints are accessed securely.
- **`rate_limiter.py`**: Prevents API abuse with throttling.

#### **`src/routes/`**
**Purpose**: Defines all HTTP routes for the backend.

- **`ai_routes.py`**: Handles AI workflows (e.g., `/api/ai/query`).
- **`healthcheck.py`**: Endpoint to verify system health (`/health`).

#### **`src/services/`**
**Purpose**: Implements core backend logic.

- **`storage/s3_storage.py`**:
  - Uploads and retrieves files (audio, transcripts, logs) from S3.

- **`database/aurora_client.py`**:
  - Manages PostgreSQL/Aurora database queries.

- **`session_manager.py`**:
  - Tracks user sessions, including context.

- **`message_router.py`**:
  - Routes queries between GPT, Claude, and Llama models.

- **`conversation_manager.py`**:
  - Maintains conversation state and history.

- **`logging_service.py`**:
  - Centralized logging logic; uploads logs to S3.

#### **`src/utils/`**
**Purpose**: Helper functions and utilities.

- **`logger.py`**: Configures and formats log outputs.
- **`s3_helper.py`**: Simplifies S3 interactions (e.g., presigned URLs).
- **`db_helper.py`**: Reusable Postgres query helpers.
- **`constants.py`**: Centralized constants for the application.

#### **`src/app.py`**
- Initializes the FastAPI application with middleware and routes.

#### **`src/main.py`**
- Entry point for the application:
  - Configures Uvicorn to start the server.

---

### **4. `tests/`**
**Purpose**: Comprehensive testing for the backend.

- **Structure**:
  - **`unit/`**:
    - Tests for individual components (e.g., GPTService).
  - **`integration/`**:
    - Tests combining multiple modules (e.g., GPT + RAG).
  - **`e2e/`**:
    - End-to-end tests simulating full workflows.

---

## **Getting Started**

## Folder Structure

```
ai_backend/
├── docs/
│   ├── api.md
│   ├── architecture.md
│   └── setup.md
├── scripts/
│   ├── start.sh
│   ├── deploy.sh
│   └── cleanup.sh
├── src/
│   ├── api/
│   │   ├── gpt/
│   │   │   ├── service.py
│   │   │   └── utils.py
│   │   ├── claude/
│   │   │   ├── service.py
│   │   │   └── utils.py
│   │   ├── llama/
│   │   │   ├── service.py
│   │   │   └── utils.py
│   │   ├── tts/
│   │   │   ├── eleven_labs.py
│   │   │   ├── google_tts.py
│   │   │   ├── gpt_realtime.py
│   │   │   └── utils.py
│   │   ├── stt/
│   │   │   ├── deepgram_service.py
│   │   │   ├── deepgram_test_service.py
│   │   │   ├── utils.py
│   │   │   └── __init__.py
│   │   └── __init__.py
│   ├── config/
│   │   ├── settings.py
│   │   ├── aws_config.py
│   │   └── __init__.py
│   ├── controllers/
│   │   ├── ai_controller.py
│   │   ├── voice_controller.py
│   │   └── __init__.py
│   ├── middleware/
│   │   ├── auth_middleware.py
│   │   ├── rate_limiter.py
│   │   ├── error_handler.py
│   │   └── __init__.py
│   ├── models/
│   │   ├── schemas.py   # All your Pydantic models go here
│   │   └── __init__.py
│   ├── routes/
│   │   ├── ai_routes_handlers.py
│   │   ├── voice_routes_handlers.py
│   │   ├── healthcheck_handlers.py
│   │   └── __init__.py
│   ├── services/
│   │   ├── storage/
│   │   │   ├── s3_storage.py  # S3 interaction logic
│   │   │   └── __init__.py
│   │   ├── database/
│   │   │   ├── aurora_client.py  # Aurora DB queries
│   │   │   └── __init__.py
│   │   ├── session_manager.py
│   │   ├── message_router.py
│   │   ├── conversation_manager.py
│   │   ├── logging_service.py  # Store logs in S3
│   │   └── __init__.py
│   ├── utils/
│   │   ├── logger.py
│   │   ├── s3_helper.py  # AWS S3 utility functions
│   │   ├── db_helper.py  # Helper for Postgres/Aurora
│   │   ├── validators.py
│   │   ├── constants.py
│   │   ├── helpers.py
│   │   └── __init__.py
│   ├── app.py
│   └── main.py
├── tests/
│   ├── unit/
│   ├── integration/
│   └── e2e/
├── .env
├── .gitignore
├── requirements.txt
├── README.md
└── pyproject.toml (if using Poetry)
```

### Prerequisites
1. Install Python 3.9+.
2. Configure AWS credentials for accessing S3 and Aurora.

### Setup
1. Clone the repository:
   ```bash
   git clone https://github.com/your-repo-name.git
   cd ai_backend
   ```
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Set up the `.env` file:
   ```plaintext
   DATABASE_URL=postgresql+asyncpg://user:password@host/dbname
   S3_BUCKET_NAME=your-s3-bucket
   GPT_API_KEY=your-gpt-api-key
   ```
4. Run the server:
   ```bash
   bash scripts/start.sh
   ```

---

## **Contributing**

1. Fork the repository.
2. Create a new feature branch (`git checkout -b feature-branch`).
3. Commit your changes (`git commit -m 'Add feature'`).
4. Push to the branch (`git push origin feature-branch`).
5. Open a pull request.

---

## **License**

This project is licensed under the MIT License. See the `LICENSE` file for details.
