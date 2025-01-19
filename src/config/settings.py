import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Database Configuration
DATABASE_URL = os.getenv("DATABASE_URL")

# AWS S3 Configuration
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME")
S3_REGION = os.getenv("S3_REGION")
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")

# GPT API Configuration
GPT_API_KEY = os.getenv("GPT_API_KEY")

# Application Settings
DEBUG = os.getenv("DEBUG", "False").lower() in ("true", "1")
APP_PORT = int(os.getenv("APP_PORT", 8000))  # Default port is 8000

# Logging Configuration
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# Other Configurations
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "*").split(",")  # CORS settings
