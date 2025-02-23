import os
import json
from dotenv import load_dotenv
from typing import Dict, Any, List, Set

# Define environment variable configuration
ENV_VARS = {
    # Database
    "DATABASE_URL": {"required": True},
    
    # AWS S3
    "AWS_ACCESS_KEY_ID": {"required": True},
    "AWS_SECRET_ACCESS_KEY": {"required": True}, 
    "S3_BUCKET_NAME": {"default": "ConvoAudioAndTranscripts"},
    "S3_REGION": {"default": "ap-south-1", "required": True},
    
    # Redis
    "REDIS_HOST": {"default": "localhost"},
    "REDIS_PORT": {"default": "6379", "type": int},
    "REDIS_PASSWORD": {"default": None},
    
    # OpenAI API
    "GPT_API_KEY": {"required": True},
    "DEFAULT_GPT_MODEL": {"default": "gpt-4o"},
    "DEFAULT_EMBEDDING_MODEL": {"default": "text-embedding-3-small"},

    # Anthropic Claude API
    "CLAUDE_API_KEY": {"required": True},
    "DEFAULT_CLAUDE_MODEL": {"default": "claude-3"},

    # Logging
    "LOG_DIR": {"default": "./logs"},
    "LOG_LEVEL": {"default": "INFO"},
    
    # Application
    "APP_PREFIX": {"default": "/api/v1"},
    "SECRET_KEY": {"default": "change-this-in-production"},
    "PERMANENT_SESSION_LIFETIME": {"default": "30", "type": int},
    "DEBUG": {"default": "False", "type": lambda x: x.lower() in ("true", "1")},
    "APP_PORT": {"default": "8000", "type": int, "validator": lambda x: 1 <= x <= 65535},
    
    # Rate Limiting
    "RATE_LIMIT_TTL": {"default": "604800", "type": int},
    "RATE_LIMIT_THRESHOLD": {"default": "100", "type": int},
    
    # Scheduler
    "SCHEDULER_INTERVAL_MINUTES": {"default": "2", "type": int},
    
    # Feature Flags
    "ENABLE_S3_UPLOADS": {"default": "true", "type": lambda x: x.lower() == "true"},
    "ENABLE_RATE_LIMITING": {"default": "true", "type": lambda x: x.lower() == "true"},
    
    # CORS
    "ALLOWED_ORIGINS": {"default": "*", "type": lambda x: x.split(",")},
    
    # WebRTC Settings
    "WEBRTC_ICE_SERVERS": {
        "default": '[{"urls": ["stun:stun.l.google.com:19302"]}]',
        "type": json.loads,
        "validator": lambda x: isinstance(x, list) and all(isinstance(s, dict) for s in x)
    },
    "WEBRTC_MAX_MESSAGE_SIZE": {"default": "1048576", "type": int},  # 1MB
    "WEBRTC_HEARTBEAT_INTERVAL": {"default": "30", "type": int},  # seconds
    "WEBRTC_CONNECTION_TIMEOUT": {"default": "300", "type": int},  # seconds
    "WEBRTC_MAX_CONNECTIONS_PER_COMPANY": {"default": "100", "type": int},
    "ENABLE_WEBRTC": {"default": "true", "type": lambda x: x.lower() == "true"},

    "DEEPGRAM_API_KEY": {"required": True},

    # ElevenLabs Configuration
    "ELEVEN_LABS_API_KEY": {"required": True},
    "VOICE_ID": {"required": True},
    
    # Audio Service Configuration
    "AUDIO_CHUNK_SIZE": {"default": "32768", "type": int},  # 32KB
    "AUDIO_MAX_TEXT_LENGTH": {"default": "500", "type": int},
    "AUDIO_CACHE_TTL": {"default": "3600", "type": int},  # 1 hour
    "AUDIO_CHUNK_DELAY": {"default": "0.01", "type": float},  # 10ms

    # Document Processing
    "DOCUMENT_BATCH_SIZE": {"default": "1000", "type": int},
    "MAX_DOCUMENT_SIZE": {"default": "10485760", "type": int},  # 10MB
    "SUPPORTED_DOCUMENT_TYPES": {
        "default": ".txt,.pdf,.docx,.doc,.html,.md,.json,.csv,.xlsx",
        "type": lambda x: set(x.split(','))
    },
    
    # Database Connections
    "DEFAULT_DB_BATCH_SIZE": {"default": "1000", "type": int},
    "DB_CONNECTION_TIMEOUT": {"default": "30", "type": int},  # seconds
    "ENABLE_DB_CONNECTION_POOLING": {"default": "true", "type": lambda x: x.lower() == "true"},

    # Qdrant Configuration
    "QDRANT_HOST": {"default": "localhost"},
    "QDRANT_PORT": {"default": "6333", "type": int},
    "QDRANT_API_KEY": {"required": True},
    "QDRANT_HTTPS": {"default": "false", "type": lambda x: x.lower() == "true"},
    "EMBEDDINGS_DIR": {"default": "./embeddings"},
    "VECTOR_DIMENSION": {"default": "1536", "type": int},
    "SEARCH_SCORE_THRESHOLD": {"default": "0.1", "type": float},
    "BATCH_SIZE": {"default": "100", "type": int},

    # OpenAI Configuration
    "OPENAI_API_KEY": {"required": True},
    "OPENAI_MODEL": {"default": "gpt-4-turbo-preview"},
    
    # RAG Configuration
    "CHUNK_SIZE": {"default": "500", "type": int},
    "CHUNK_OVERLAP": {"default": "50", "type": int},
    "RETRIEVAL_K": {"default": "3", "type": int},
    "SCORE_THRESHOLD": {"default": "0.2", "type": float},
    "MAX_TOKENS": {"default": "4000", "type": int},
    
    # Model Configuration
    "EMBEDDING_MODEL": {"default": "text-embedding-3-small"},
    "TEMPERATURE": {"default": "0.1", "type": float},

    # Vector Store Configuration
    "VECTOR_STORE_PATH": {"default": "./vector_store", "type": str},
    "OPENAI_EMBEDDING_MODEL": {"default": "text-embedding-3-small"},
    "DEFAULT_CONFIDENCE_THRESHOLD": {"default": "0.7", "type": float},
    
    # Caching Configuration
    "EMBEDDING_CACHE_SIZE": {"default": "2000", "type": int},
    "EMBEDDING_CACHE_TTL": {"default": "3600", "type": int},  # 1 hour
    "EMBEDDING_BATCH_SIZE": {"default": "5", "type": int},
    "MAX_CONCURRENT_EMBEDDINGS": {"default": "5", "type": int},

    # Calendar Service Configuration
    "GOOGLE_SERVICE_ACCOUNT_FILE": {"required": True},
    "GOOGLE_CALENDAR_ID": {"required": True},
    "MICROSOFT_CLIENT_ID": {"required": True},
    "MICROSOFT_CLIENT_SECRET": {"required": False},  # Not needed for public auth flow
    "CALENDLY_TOKEN": {"required": False},
    
    # Calendar Defaults
    "DEFAULT_TIMEZONE": {"default": "UTC"},
    "CALENDAR_TOKEN_STORE_PATH": {"default": "~/.calendar_tokens"},
    "CALENDAR_BUFFER_MINUTES": {"default": "5", "type": int},
    "MIN_APPOINTMENT_DURATION": {"default": "30", "type": int},
    "MAX_APPOINTMENT_DURATION": {"default": "120", "type": int},
    
    # Working Hours (JSON string)
    "WORKING_HOURS": {
        "default": json.dumps({
            'monday': {'start': '09:00', 'end': '17:00'},
            'tuesday': {'start': '09:00', 'end': '17:00'},
            'wednesday': {'start': '09:00', 'end': '17:00'},
            'thursday': {'start': '09:00', 'end': '17:00'},
            'friday': {'start': '09:00', 'end': '17:00'}
        }),
        "type": json.loads
    },
    
    # Cache Settings
    "CALENDAR_CACHE_TTL": {"default": "3600", "type": int},  # 1 hour
    "CALENDAR_CACHE_SIZE": {"default": "1000", "type": int},
    
    # Rate Limiting
    "CALENDAR_RATE_LIMIT_PER_MINUTE": {"default": "60", "type": int},
    "CALENDAR_MAX_CONCURRENT_OPERATIONS": {"default": "5", "type": int},
}

# Rest of your existing code remains unchanged
def reload_environment() -> None:
   """Reload all environment variables from .env file"""
   # First unload current env vars
   for key in list(os.environ.keys()):
       if key in ENV_VARS:
           del os.environ[key]
   
   # Reload from .env file
   load_dotenv(override=True)

def get_env_var(key: str, config: Dict[str, Any]) -> Any:
   """
   Get environment variable with proper error handling and type conversion
   """
   value = os.getenv(key, config.get("default"))
   
   if config.get("required", False) and not value:
       raise ValueError(f"{key} is required but not set.")
       
   if value is not None and "type" in config:
       try:
           value = config["type"](value)
           if "validator" in config and not config["validator"](value):
               raise ValueError(f"{key} failed validation")
       except ValueError as e:
           raise ValueError(f"Invalid value for {key}: {e}")
           
   return value

# Load environment variables
reload_environment()

# Initialize all variables
env_values = {}
for key, config in ENV_VARS.items():
   env_values[key] = get_env_var(key, config)

# Create global variables
globals().update(env_values)

# Ensure log directory exists
try:
   os.makedirs(LOG_DIR, exist_ok=True)
except OSError as e:
   raise RuntimeError(f"Failed to create log directory at {LOG_DIR}: {e}")

# Set derived values
LOG_FILE_PATH = os.path.join(LOG_DIR, "app.log")

def get_config_dict() -> Dict[str, Any]:
   """
   Get a dictionary of all configuration values for debugging
   """
   sensitive_keys = {"DATABASE_URL", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", 
                    "GPT_API_KEY", "SECRET_KEY", "REDIS_PASSWORD"}
   return {
       key: "*****" if key in sensitive_keys else value 
       for key, value in env_values.items()
   }

# Print Configurations for Debugging
if env_values.get("DEBUG"):
   print("Current Configuration:")
   for key, value in get_config_dict().items():
       print(f"{key}: {value}")

def generate_env_template() -> str:
   """Generate a template .env file based on configuration"""
   template = ["# Environment Variables Template\n"]
   
   for key, config in ENV_VARS.items():
       comment = []
       if config.get("required"):
           comment.append("Required")
       if "default" in config:
           comment.append(f"Default: {config['default']}")
           
       if comment:
           template.append(f"# {', '.join(comment)}")
       template.append(f"{key}=\n")
       
   return "\n".join(template)

__all__ = list(ENV_VARS.keys()) + [
    'LOG_FILE_PATH',
    'reload_environment',
    'get_config_dict',
    'generate_env_template'
]

"""
Added new WebRTC-specific environment variables:

WEBRTC_ICE_SERVERS: JSON string for ICE server configuration
WEBRTC_MAX_MESSAGE_SIZE: Maximum WebSocket message size
WEBRTC_HEARTBEAT_INTERVAL: Interval for connection heartbeats
WEBRTC_CONNECTION_TIMEOUT: Connection timeout duration
WEBRTC_MAX_CONNECTIONS_PER_COMPANY: Connection limit per company
ENABLE_WEBRTC: Feature flag for WebRTC functionality


Added proper type conversion and validation:

JSON parsing for ICE servers configuration
Integer conversion for numeric values
Validation for ICE servers format

Calendar Integration Settings:

1. Service Authentication:
   - GOOGLE_SERVICE_ACCOUNT_FILE: Path to Google service account JSON
   - GOOGLE_CALENDAR_ID: Google Calendar ID
   - MICROSOFT_CLIENT_ID: Microsoft OAuth client ID
   - MICROSOFT_CLIENT_SECRET: Optional for public auth flow
   - CALENDLY_TOKEN: Optional Calendly API token

2. Calendar Operation Settings:
   - DEFAULT_TIMEZONE: Default timezone for calendar operations
   - CALENDAR_TOKEN_STORE_PATH: Path to store authentication tokens
   - CALENDAR_BUFFER_MINUTES: Buffer time between appointments
   - MIN_APPOINTMENT_DURATION: Minimum duration for appointments
   - MAX_APPOINTMENT_DURATION: Maximum duration for appointments
   - WORKING_HOURS: JSON string defining working hours per day

3. Performance and Caching:
   - CALENDAR_CACHE_TTL: Token cache time-to-live
   - CALENDAR_CACHE_SIZE: Maximum cache size
   - CALENDAR_RATE_LIMIT_PER_MINUTE: API rate limiting
   - CALENDAR_MAX_CONCURRENT_OPERATIONS: Concurrent operation limit
"""