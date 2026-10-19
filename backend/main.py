import os
import sys
from pathlib import Path

# Support both `uvicorn backend.main:app` and the existing backend-directory launch.
if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import boto3

from dotenv import load_dotenv
from botocore.config import Config
from fastapi import Depends, FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, EmailStr, Field
from supabase import create_client
from fastapi.middleware.cors import CORSMiddleware
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("SUPABASE_URL and SUPABASE_KEY must be set in backend/.env")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

AWS_REGION = os.getenv("AWS_REGION")
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME")

if not AWS_REGION or not S3_BUCKET_NAME:
    raise RuntimeError("AWS_REGION and S3_BUCKET_NAME must be set in backend/.env")

s3 = boto3.client(
    "s3",
    region_name=AWS_REGION,
    aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
    config=Config(
        signature_version="s3v4",
        s3={"addressing_style": "virtual"},
    ),
)

app = FastAPI(
    title="Ataraxia API",
    description="Backend API for the Ataraxia recommendation system",
    version="0.2.0"
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8081",
        "http://127.0.0.1:8081",
        "http://localhost:8082",
        "http://127.0.0.1:8082",
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
security = HTTPBearer()


class AuthRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


@app.get("/")
def root():
    return {"message": "Welcome to the Ataraxia API"}


@app.get("/health")
def health_check():
    return {"status": "healthy"}


@app.post("/auth/signup")
def signup(request: AuthRequest):
    try:
        response = supabase.auth.sign_up({"email": str(request.email), "password": request.password })

        if response.user is None:
            raise HTTPException( status_code=400, detail="Signup could not be completed.")

        result = {
            "message": "Signup request received.",
            "user": {
                "id": str(response.user.id),
                "email": response.user.email
            },
            "requires_email_confirmation": response.session is None
        }

        if response.session is not None:
            result["access_token"] = response.session.access_token
            result["refresh_token"] = response.session.refresh_token

        return result

    except HTTPException:
        raise
   
    except Exception as error:
        print("Signup error:", repr(error))

        error_message = str(error).lower()

        if "user already registered" in error_message:
            raise HTTPException( status_code=409, detail="An account with this email already exists. Please log in instead.")

        if "email rate limit exceeded" in error_message:
            raise HTTPException( status_code=429, detail="Too many signup attempts. Please try again later.")

        raise HTTPException(status_code=400,detail="Signup failed. Please check your details and try again.")


@app.post("/auth/login")
def login(request: AuthRequest):
    try:
        response = supabase.auth.sign_in_with_password({
            "email": str(request.email),
            "password": request.password
        })

        if response.user is None or response.session is None:
            raise HTTPException(
                status_code=401,
                detail="Login failed."
            )

        return {
            "message": "Login successful.",
            "user": {
                "id": str(response.user.id),
                "email": response.user.email
            },
            "access_token": response.session.access_token,
            "refresh_token": response.session.refresh_token,
            "token_type": "bearer"
        }

    except HTTPException:
        raise
    except Exception:
        raise HTTPException( status_code=401, detail="Invalid credentials or login unsuccessful.")


@app.post("/auth/refresh")
def refresh_session(request: dict):
    refresh_token = request.get("refresh_token")

    if not isinstance(refresh_token, str) or not refresh_token.strip():
        raise HTTPException(status_code=400, detail="A refresh token is required.")

    try:
        response = supabase.auth.refresh_session(refresh_token)

        if response.user is None or response.session is None:
            raise HTTPException(status_code=401, detail="Session expired. Please log in again.")

        return {
            "message": "Session refreshed.",
            "user": {
                "id": str(response.user.id),
                "email": response.user.email
            },
            "access_token": response.session.access_token,
            "refresh_token": response.session.refresh_token,
            "token_type": "bearer"
        }

    except HTTPException:
        raise
    except Exception:
        raise HTTPException( status_code=401, detail="Session expired or refresh token is invalid. Please log in again.")


@app.get("/auth/me")
def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    try:
        response = supabase.auth.get_user(credentials.credentials)

        if response.user is None:
            raise HTTPException( status_code=401, detail="Invalid or expired access token.")

        return {
            "id": str(response.user.id),
            "email": response.user.email
        }

    except HTTPException:
        raise
    except Exception:
        raise HTTPException( status_code=401, detail="Invalid or expired access token.")


from backend.onboarding.api import create_router
app.include_router(create_router(get_current_user))


@app.get("/videos/{video_key}/playback")
def get_video_playback_url(video_key: str, credentials: HTTPAuthorizationCredentials = Depends(security),):
    # Verify that the user has a valid Supabase session.
    try:
        response = supabase.auth.get_user(credentials.credentials)

        if response.user is None:
            raise HTTPException(status_code=401, detail="Invalid or expired access token.",)

    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired access token.",)

    # Allow only the video uploaded for our initial playback test.
    if video_key != "_bjglEyMaeo.mp4":
        raise HTTPException(status_code=404, detail="Video not found.",)

    try:
        playback_url = s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": S3_BUCKET_NAME, "Key": video_key,},
            ExpiresIn=300,
        )

        return { "video_key": video_key, "playback_url": playback_url, "expires_in": 300,}

    except Exception:
        raise HTTPException(status_code=500, detail="Could not generate video playback URL.",)



@app.get("/videos/feed")
def get_video_feed(credentials: HTTPAuthorizationCredentials = Depends(security),):
    # Verify that the user has a valid Supabase session.
    try:
        response = supabase.auth.get_user(credentials.credentials)

        if response.user is None:
            raise HTTPException(status_code=401, detail="Invalid or expired access token.",)

    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired access token.",)

    videos = []

    try:
        paginator = s3.get_paginator("list_objects_v2")

        for page in paginator.paginate(Bucket=S3_BUCKET_NAME):
            for item in page.get("Contents", []):
                video_key = item["Key"]

                if not video_key.lower().endswith(".mp4"):
                    continue

                playback_url = s3.generate_presigned_url(
                    "get_object",
                    Params={ "Bucket": S3_BUCKET_NAME, "Key": video_key,},
                    ExpiresIn=300,
                )

                videos.append({ "video_key": video_key, "playback_url": playback_url,})

        videos.sort(key=lambda video: video["video_key"].lower())
        return {"videos": videos,"count": len(videos),}

    except Exception:
        raise HTTPException(status_code=500, detail="Could not load the video feed.",)
