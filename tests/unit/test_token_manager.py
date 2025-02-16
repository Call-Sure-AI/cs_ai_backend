import pytest
import os
from datetime import datetime, UTC
import json
import logging
from src.services.calendar.token_manager import TokenManager

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@pytest.fixture
def token_manager():
    """Fixture to create a test TokenManager instance"""
    tm = TokenManager("test_tokens")
    yield tm
    # Cleanup after tests
    if os.path.exists(tm.token_store_path):
        os.remove(tm.token_store_path)

def test_save_and_load_token(token_manager):
    """Test saving and loading a token"""
    # Test data
    test_token = {
        "access_token": "test_token_123",
        "expires_in": 3600,
        "timestamp": datetime.now(UTC).isoformat()
    }
    
    try:
        # Test saving
        token_manager.save_token("test_service", test_token)
        
        # Test loading
        loaded_token = token_manager.load_token("test_service")
        
        assert loaded_token is not None
        assert loaded_token["access_token"] == test_token["access_token"]
        assert loaded_token["expires_in"] == test_token["expires_in"]
        
    except Exception as e:
        logger.error(f"Test failed: {e}")
        raise

def test_token_file_content(token_manager):
    """Test the structure of the token file"""
    test_token = {
        "access_token": "test_token_123",
        "expires_in": 3600
    }
    
    try:
        token_manager.save_token("test_service", test_token)
        
        # Read file directly
        with open(token_manager.token_store_path, 'r') as f:
            file_content = json.load(f)
            
        assert "test_service" in file_content
        assert "data" in file_content["test_service"]
        assert "updated_at" in file_content["test_service"]
        
    except Exception as e:
        logger.error(f"Test failed: {e}")
        raise

def test_multiple_services(token_manager):
    """Test handling multiple services"""
    tokens = {
        "service1": {"access_token": "token1", "expires_in": 3600},
        "service2": {"access_token": "token2", "expires_in": 7200}
    }
    
    try:
        # Save tokens for multiple services
        for service, token in tokens.items():
            token_manager.save_token(service, token)
        
        # Verify each service
        for service, token in tokens.items():
            loaded = token_manager.load_token(service)
            assert loaded["access_token"] == token["access_token"]
            
    except Exception as e:
        logger.error(f"Test failed: {e}")
        raise

def test_token_update(token_manager):
    """Test updating an existing token"""
    service = "test_service"
    original_token = {"access_token": "original", "expires_in": 3600}
    updated_token = {"access_token": "updated", "expires_in": 7200}
    
    try:
        # Save original token
        token_manager.save_token(service, original_token)
        
        # Update token
        token_manager.save_token(service, updated_token)
        
        # Verify update
        loaded_token = token_manager.load_token(service)
        assert loaded_token["access_token"] == "updated"
        
    except Exception as e:
        logger.error(f"Test failed: {e}")
        raise

def test_clear_token(token_manager):
    """Test clearing a specific token"""
    tokens = {
        "service1": {"access_token": "token1"},
        "service2": {"access_token": "token2"}
    }
    
    try:
        # Save multiple tokens
        for service, token in tokens.items():
            token_manager.save_token(service, token)
        
        # Clear one token
        result = token_manager.clear_token("service1")
        assert result is True
        
        # Verify service1 token is gone but service2 remains
        assert token_manager.load_token("service1") is None
        assert token_manager.load_token("service2") is not None
        
    except Exception as e:
        logger.error(f"Test failed: {e}")
        raise

def test_clear_all_tokens(token_manager):
    """Test clearing all tokens"""
    tokens = {
        "service1": {"access_token": "token1"},
        "service2": {"access_token": "token2"}
    }
    
    try:
        # Save multiple tokens
        for service, token in tokens.items():
            token_manager.save_token(service, token)
        
        # Clear all tokens
        result = token_manager.clear_all_tokens()
        assert result is True
        
        # Verify all tokens are gone
        assert token_manager.load_token("service1") is None
        assert token_manager.load_token("service2") is None
        assert not os.path.exists(token_manager.token_store_path)
        
    except Exception as e:
        logger.error(f"Test failed: {e}")
        raise

def test_platform_detection(token_manager):
    """Test platform detection"""
    platform = token_manager.platform
    assert platform in ["windows", "unix"]

def test_error_handling(token_manager):
    """Test error handling scenarios"""
    try:
        # Test loading from non-existent file
        assert token_manager.load_token("nonexistent") is None
        
        # Test loading with corrupted file
        with open(token_manager.token_store_path, 'w') as f:
            f.write("corrupted json{")
        
        assert token_manager.load_token("test") is None
        
    except Exception as e:
        logger.error(f"Test failed: {e}")
        raise

def test_concurrent_access(token_manager):
    """Test concurrent access to token file"""
    import threading
    
    def worker(service: str):
        try:
            token = {"access_token": f"token_{service}"}
            token_manager.save_token(service, token)
            loaded = token_manager.load_token(service)
            assert loaded["access_token"] == f"token_{service}"
        except Exception as e:
            logger.error(f"Worker failed: {e}")
            raise
    
    try:
        # Create multiple threads
        threads = []
        for i in range(5):
            t = threading.Thread(target=worker, args=(f"service_{i}",))
            threads.append(t)
            t.start()
        
        # Wait for all threads to complete
        for t in threads:
            t.join()
            
    except Exception as e:
        logger.error(f"Test failed: {e}")
        raise