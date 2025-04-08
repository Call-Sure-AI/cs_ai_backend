import os
import json
from typing import Dict, List, Union, ClassVar, Any, Set, Optional
from dotenv import load_dotenv
from pydantic_settings import BaseSettings

# Load environment variables from .env file
load_dotenv()

# Environment variable configuration definition
ENV_VARS = {
   # Database
   "DATABASE_URL": {"required": False},  # Will be constructed if not provided
   "DATABASE_USER": {"default": "dev-db_owner"},
   "DATABASE_PASSWORD": {"default": "gtsiDS54rjOE"},
   "DATABASE_HOST": {"default": "ep-spring-bar-a1wq2cbf.ap-southeast-1.aws.neon.tech"},
   "DATABASE_NAME": {"default": "dev-db"},
   
   # AWS S3
   "AWS_ACCESS_KEY_ID": {"required": False},
   "AWS_SECRET_ACCESS_KEY": {"required": False}, 
   "S3_BUCKET_NAME": {"default": "ConvoAudioAndTranscripts"},
   "S3_REGION": {"default": "ap-south-1", "required": False},
   
   # Redis
   "REDIS_HOST": {"default": "localhost"},
   "REDIS_PORT": {"default": "6379", "type": int},
   "REDIS_PASSWORD": {"default": None},
   "REDIS_CACHE_TTL": {"default": "300", "type": int},
   
   # OpenAI API
   "GPT_API_KEY": {"required": False},
   "DEFAULT_GPT_MODEL": {"default": "gpt-4o"},
   "DEFAULT_EMBEDDING_MODEL": {"default": "text-embedding-3-small"},
   
   # Logging
   "LOG_DIR": {"default": "./logs"},
   "LOG_LEVEL": {"default": "INFO"},
   
   # Application
   "APP_PREFIX": {"default": "/api/v1"},
   "SECRET_KEY": {"default": "change-this-in-production"},
   "PERMANENT_SESSION_LIFETIME": {"default": "30", "type": int},
   "DEBUG": {"default": "True", "type": lambda x: x.lower() in ("true", "1")},
   "HOST": {"default": "0.0.0.0"},
   "PORT": {"default": "8000", "type": int},
   "WORKERS": {"default": "1", "type": int},
   
   # Rate Limiting
   "RATE_LIMIT_TTL": {"default": "604800", "type": int},
   "RATE_LIMIT_THRESHOLD": {"default": "100", "type": int},
   
   # Scheduler
   "SCHEDULER_INTERVAL_MINUTES": {"default": "2", "type": int},
   
   # Feature Flags
   "ENABLE_S3_UPLOADS": {"default": "true", "type": lambda x: x.lower() == "true"},
   "ENABLE_RATE_LIMITING": {"default": "true", "type": lambda x: x.lower() == "true"},
   
   # CORS
   "ALLOWED_ORIGINS": {"default": "*,http://localhost,http://localhost:8000,http://localhost:3000,http://127.0.0.1:8000,http://127.0.0.1:3000", "type": lambda x: x.split(",")},
   
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

    # Deepgram
    "DEEPGRAM_API_KEY": {"required": False},

    # ElevenLabs Configuration
    "ELEVEN_LABS_API_KEY": {"required": False},
    "VOICE_ID": {"default": "default"},
    
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
    "QDRANT_HOST": {"default": "qdrant.callsure.ai"},
    "QDRANT_PORT": {"default": "443", "type": int},
    "QDRANT_GRPC_PORT": {"default": "6334", "type": int},
    "QDRANT_API_KEY": {"default": "68cd8841-53bd-439a-aafe-be4b32812943"},
    "QDRANT_HTTPS": {"default": "true", "type": lambda x: x.lower() == "true"},
    "EMBEDDINGS_DIR": {"default": "./embeddings"},
    "VECTOR_DIMENSION": {"default": "1536", "type": int},
    "SEARCH_SCORE_THRESHOLD": {"default": "0.1", "type": float},
    "BATCH_SIZE": {"default": "100", "type": int},

    # OpenAI Configuration
    "OPENAI_API_KEY": {"required": True},
    "OPENAI_MODEL": {"default": "gpt-4"},
    
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
    "VECTOR_STORE_PATH": {"default": "chroma_db"},
    "OPENAI_EMBEDDING_MODEL": {"default": "text-embedding-3-small"},
    "DEFAULT_CONFIDENCE_THRESHOLD": {"default": "0.7", "type": float},
    "VECTOR_SEARCH_TIMEOUT": {"default": "1.0", "type": float},
    
    # Caching Configuration
    "EMBEDDING_CACHE_SIZE": {"default": "2000", "type": int},
    "EMBEDDING_CACHE_TTL": {"default": "3600", "type": int},  # 1 hour
    "EMBEDDING_BATCH_SIZE": {"default": "5", "type": int},
    "MAX_CONCURRENT_EMBEDDINGS": {"default": "5", "type": int},
    "CACHE_EMBEDDINGS": {"default": "true", "type": lambda x: x.lower() == "true"},
    "PRELOAD_AGENTS": {"default": "true", "type": lambda x: x.lower() == "true"},
    "RESPONSE_CACHE_SIZE": {"default": "1000", "type": int},
    "USE_NUMPY_SEARCH": {"default": "true", "type": lambda x: x.lower() == "true"},
    "BATCH_REQUESTS": {"default": "true", "type": lambda x: x.lower() == "true"},

    # Calendar Service Configuration
    "GOOGLE_SERVICE_ACCOUNT_FILE": {"required": False},
    "GOOGLE_CALENDAR_ID": {"required": False},
    "MICROSOFT_CLIENT_ID": {"required": False},
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
    
    # Twilio
    "TWILIO_ACCOUNT_SID": {"required": False},
    "TWILIO_AUTH_TOKEN": {"required": False},
    "TWILIO_PHONE_NUMBER": {"required": False},
    
    # WebSocket
    "WS_HEARTBEAT_INTERVAL": {"default": "30", "type": int},
    
    # Agent Configuration
    "MAX_RESPONSE_TOKENS": {"default": "200", "type": int},
    "RESPONSE_TIMEOUT": {"default": "15.0", "type": float},
}

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

# Initialize all variables
env_values = {}
for key, config in ENV_VARS.items():
    env_values[key] = get_env_var(key, config)

# Ensure log directory exists
try:
    os.makedirs(env_values["LOG_DIR"], exist_ok=True)
except OSError as e:
    print(f"Warning: Failed to create log directory at {env_values['LOG_DIR']}: {e}")

# Set derived values
LOG_FILE_PATH = os.path.join(env_values["LOG_DIR"], "app.log")

# Create Pydantic settings class
class Settings(BaseSettings):
    # Database Settings
    DATABASE_URL: str = env_values.get("DATABASE_URL", "")
    DATABASE_USER: str = env_values.get("DATABASE_USER", "dev-db_owner")
    DATABASE_PASSWORD: str = env_values.get("DATABASE_PASSWORD", "gtsiDS54rjOE")
    DATABASE_HOST: str = env_values.get("DATABASE_HOST", "ep-spring-bar-a1wq2cbf.ap-southeast-1.aws.neon.tech")
    DATABASE_NAME: str = env_values.get("DATABASE_NAME", "dev-db")
    
    # API Settings
    DEBUG: bool = env_values.get("DEBUG", True)
    HOST: str = env_values.get("HOST", "0.0.0.0")
    PORT: int = env_values.get("PORT", 8000)
    WORKERS: int = env_values.get("WORKERS", 1)
    APP_PREFIX: str = env_values.get("APP_PREFIX", "/api/v1")
    SECRET_KEY: str = env_values.get("SECRET_KEY", "change-this-in-production")
    
    # CORS Settings
    # ALLOWED_ORIGINS: List[str] = env_values.get("ALLOWED_ORIGINS", ["*"])
    @property
    def ALLOWED_ORIGINS(self) -> List[str]:
        """Process ALLOWED_ORIGINS separately to avoid JSON parsing issues"""
        origins = os.getenv("ALLOWED_ORIGINS", "*")
        if origins:
            return origins.split(",")
        return ["*"]
    
    
    # OpenAI
    OPENAI_API_KEY: str = env_values.get("OPENAI_API_KEY", "")
    OPENAI_MODEL: str = env_values.get("OPENAI_MODEL", "gpt-4")
    OPENAI_EMBEDDING_MODEL: str = env_values.get("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
    
    # Qdrant Settings
    QDRANT_HOST: str = env_values.get("QDRANT_HOST", "qdrant.callsure.ai")
    QDRANT_PORT: int = env_values.get("QDRANT_PORT", 443)
    QDRANT_GRPC_PORT: int = env_values.get("QDRANT_GRPC_PORT", 6334)
    QDRANT_API_KEY: str = env_values.get("QDRANT_API_KEY", "68cd8841-53bd-439a-aafe-be4b32812943")
    QDRANT_HTTPS: bool = env_values.get("QDRANT_HTTPS", True)
    
    # Redis
    REDIS_HOST: str = env_values.get("REDIS_HOST", "localhost")
    REDIS_PORT: int = env_values.get("REDIS_PORT", 6379)
    REDIS_PASSWORD: Optional[str] = env_values.get("REDIS_PASSWORD", "")
    REDIS_CACHE_TTL: int = env_values.get("REDIS_CACHE_TTL", 300)  # 5 minutes
    
    # Vector Store Settings
    VECTOR_STORE_PATH: str = env_values.get("VECTOR_STORE_PATH", "chroma_db")
    VECTOR_SEARCH_TIMEOUT: float = env_values.get("VECTOR_SEARCH_TIMEOUT", 1.0)
    EMBEDDING_BATCH_SIZE: int = env_values.get("EMBEDDING_BATCH_SIZE", 32)
    
    # RAG Configuration
    CHUNK_SIZE: int = env_values.get("CHUNK_SIZE", 500)
    CHUNK_OVERLAP: int = env_values.get("CHUNK_OVERLAP", 50)
    RETRIEVAL_K: int = env_values.get("RETRIEVAL_K", 3)
    SCORE_THRESHOLD: float = env_values.get("SCORE_THRESHOLD", 0.2)
    
    # Audio
    ELEVEN_LABS_API_KEY: str = env_values.get("ELEVEN_LABS_API_KEY", "")
    VOICE_ID: str = env_values.get("VOICE_ID", "default")
    
    # WebSocket
    WS_HEARTBEAT_INTERVAL: int = env_values.get("WS_HEARTBEAT_INTERVAL", 30)  # seconds
    
    # Agent Configuration
    DEFAULT_CONFIDENCE_THRESHOLD: float = env_values.get("DEFAULT_CONFIDENCE_THRESHOLD", 0.7)
    MAX_RESPONSE_TOKENS: int = env_values.get("MAX_RESPONSE_TOKENS", 200)
    RESPONSE_TIMEOUT: float = env_values.get("RESPONSE_TIMEOUT", 15.0)
    
    # Performance Optimization
    CACHE_EMBEDDINGS: bool = env_values.get("CACHE_EMBEDDINGS", True)
    PRELOAD_AGENTS: bool = env_values.get("PRELOAD_AGENTS", True)
    RESPONSE_CACHE_SIZE: int = env_values.get("RESPONSE_CACHE_SIZE", 1000)
    USE_NUMPY_SEARCH: bool = env_values.get("USE_NUMPY_SEARCH", True)
    BATCH_REQUESTS: bool = env_values.get("BATCH_REQUESTS", True)
    
    # Twilio
    TWILIO_ACCOUNT_SID: str = env_values.get("TWILIO_ACCOUNT_SID", "")
    TWILIO_AUTH_TOKEN: str = env_values.get("TWILIO_AUTH_TOKEN", "")
    TWILIO_PHONE_NUMBER: str = env_values.get("TWILIO_PHONE_NUMBER", "")
    
    # Image Settings
    IMAGE_SETTINGS: ClassVar[Dict[str, Union[List[str], int, str, Dict[str, str]]]] = {
        'SUPPORTED_FORMATS': ['image/jpeg', 'image/png', 'image/gif'],
        'MAX_FILE_SIZE': 10 * 1024 * 1024,  # 10MB
        'STORAGE_PATH': 'storage/images',
        'EMBEDDING_CACHE_PATH': 'storage/embeddings',
        'MODEL_CONFIG': {
            'vision_model': 'Salesforce/blip2-opt-2.7b',
            'embedding_model': 'text-embedding-3-small'
        }
    }
    
    def get_database_url(self) -> str:
        """Construct database URL if not provided explicitly"""
        if self.DATABASE_URL:
            return self.DATABASE_URL
            
        return f"postgresql://{self.DATABASE_USER}:{self.DATABASE_PASSWORD}@{self.DATABASE_HOST}/{self.DATABASE_NAME}?sslmode=require"
    
    class Config:
        env_file = ".env"
        
    def model_post_init(self, *args, **kwargs):
        """Post initialization hook to set DATABASE_URL if not provided"""
        if not self.DATABASE_URL:
            self.DATABASE_URL = self.get_database_url()

# Create settings instance
settings = Settings()

# Make env_values available globally
for key, value in env_values.items():
    globals()[key] = value

def get_config_dict() -> Dict[str, Any]:
    """Get a dictionary of all configuration values for debugging"""
    sensitive_keys = {"DATABASE_URL", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", 
                     "GPT_API_KEY", "SECRET_KEY", "REDIS_PASSWORD", "OPENAI_API_KEY"}
    return {
        key: "*****" if key in sensitive_keys else value 
        for key, value in env_values.items()
    }

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

# Print Configurations for Debugging if DEBUG mode is enabled
if DEBUG:
    print("Current Configuration:")
    config_dict = get_config_dict()
    for key, value in sorted(config_dict.items()):
        print(f"{key}: {value}")

__all__ = list(ENV_VARS.keys()) + [
    'LOG_FILE_PATH',
    'get_config_dict',
    'generate_env_template',
    'settings'
]