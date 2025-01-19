import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Ensure directories
LOG_DIR = os.getenv("LOG_DIR", "./logs")
try:
    os.makedirs(LOG_DIR, exist_ok=True)
except OSError as e:
    raise RuntimeError(f"Failed to create log directory at {LOG_DIR}: {e}")

# Database Configuration
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL is required but not set.")

# AWS S3 Configuration
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
if not AWS_ACCESS_KEY_ID or not AWS_SECRET_ACCESS_KEY:
    raise ValueError("AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY are required.")

S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME", "ConvoAudioAndTranscripts")
S3_REGION = os.getenv("S3_REGION", "ap-south-1")
if not S3_REGION:
    raise ValueError("S3_REGION is required but not set.")

# Redis Configuration
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", None)

# OpenAI API Configuration
GPT_API_KEY = os.getenv("GPT_API_KEY")
if not GPT_API_KEY:
    raise ValueError("GPT_API_KEY is required but not set.")

DEFAULT_GPT_MODEL = os.getenv("DEFAULT_GPT_MODEL", "gpt-4o")  # Default GPT model
DEFAULT_EMBEDDING_MODEL = os.getenv("DEFAULT_EMBEDDING_MODEL", "text-embedding-3-small")  # Default embedding model

# Logging Configuration
LOG_FILE_PATH = os.path.join(LOG_DIR, "app.log")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# Application Settings
APP_PREFIX = os.getenv("APP_PREFIX", "/api/v1")
SECRET_KEY = os.getenv("SECRET_KEY", "change-this-in-production")
PERMANENT_SESSION_LIFETIME = int(os.getenv("PERMANENT_SESSION_LIFETIME", 30))  # in minutes
DEBUG = os.getenv("DEBUG", "False").lower() in ("true", "1")
APP_PORT = int(os.getenv("APP_PORT", 8000))
if not (1 <= APP_PORT <= 65535):
    raise ValueError("APP_PORT must be between 1 and 65535.")

# Rate Limiting Configuration
RATE_LIMIT_TTL = int(os.getenv("RATE_LIMIT_TTL", 604800))  # 7 days in seconds
RATE_LIMIT_THRESHOLD = int(os.getenv("RATE_LIMIT_THRESHOLD", 100))  # Default to 100 requests

# Scheduler Settings
SCHEDULER_INTERVAL_MINUTES = int(os.getenv("SCHEDULER_INTERVAL_MINUTES", 2))

# Feature Flags
ENABLE_S3_UPLOADS = os.getenv("ENABLE_S3_UPLOADS", "true").lower() == "true"
ENABLE_RATE_LIMITING = os.getenv("ENABLE_RATE_LIMITING", "true").lower() == "true"

# Other Configurations
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "*").split(",")  # CORS settings

# Print Configurations for Debugging
if DEBUG:
    print("Current Configuration:")
    print(f"DATABASE_URL: {'*****' if DATABASE_URL else 'NOT SET'}")
    print(f"REDIS_HOST: {REDIS_HOST}:{REDIS_PORT}")
    print(f"S3_BUCKET_NAME: {S3_BUCKET_NAME}")
    print(f"LOG_LEVEL: {LOG_LEVEL}")
    print(f"APP_PREFIX: {APP_PREFIX}")
    print(f"Default GPT Model: {DEFAULT_GPT_MODEL}")
    print(f"Default Embedding Model: {DEFAULT_EMBEDDING_MODEL}")
    print(f"DEBUG: {DEBUG}")
