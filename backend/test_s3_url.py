
import os
import boto3
import urllib.request
import urllib.error
from dotenv import load_dotenv
from botocore.config import Config

load_dotenv(override=True)

s3 = boto3.client(
    "s3",
    region_name=os.getenv("AWS_REGION"),
    aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
    config=Config(
        signature_version="s3v4",
        s3={"addressing_style": "virtual"},
    ),
)

url = s3.generate_presigned_url(
    "get_object",
    Params={
        "Bucket": os.getenv("S3_BUCKET_NAME"),
        "Key": "_bjglEyMaeo.mp4",
    },
    ExpiresIn=300,
)

request = urllib.request.Request(
    url,
    headers={"Range": "bytes=0-0"},
)

try:
    response = urllib.request.urlopen(request, timeout=30)
    print("Presigned URL test: SUCCESS")
    print("HTTP status:", response.status)
    print("Video accessible:", len(response.read(1)) == 1)

except urllib.error.HTTPError as error:
    import xml.etree.ElementTree as ET

    root = ET.fromstring(error.read())
    print("Presigned URL test: FAILED")
    print("HTTP status:", error.code)
    print("AWS error code:", root.findtext("Code", "Unknown"))
    print("AWS error message:", root.findtext("Message", "No message"))
