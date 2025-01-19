import os
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
   "ALLOWED_ORIGINS": {"default": "*", "type": lambda x: x.split(",")}
}

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