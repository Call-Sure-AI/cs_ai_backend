import boto3
import os
from botocore.exceptions import NoCredentialsError

AWS_ACCESS_KEY = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
AWS_BUCKET_NAME = os.getenv("AWS_S3_BUCKET")
AWS_REGION = os.getenv("AWS_S3_REGION")

def upload_to_s3(file_path: str, file_name: str) -> str:
    """Uploads a file to S3 and returns the file URL."""
    try:
        s3 = boto3.client("s3", aws_access_key_id=AWS_ACCESS_KEY, aws_secret_access_key=AWS_SECRET_KEY, region_name=AWS_REGION)

        s3.upload_file(file_path, AWS_BUCKET_NAME, file_name, ExtraArgs={"ACL": "public-read", "ContentType": "audio/webm"})

        file_url = f"https://{AWS_BUCKET_NAME}.s3.{AWS_REGION}.amazonaws.com/{file_name}"
        return file_url
    except NoCredentialsError:
        return "AWS credentials not found"
    except Exception as e:
        return str(e)
