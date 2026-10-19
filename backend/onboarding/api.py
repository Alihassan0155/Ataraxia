"""Routes use the existing Supabase-verified identity dependency."""
import os
from typing import Annotated
from uuid import UUID
from fastapi import APIRouter,Depends,HTTPException,Query
from pydantic import BaseModel,ConfigDict,Field,field_validator
from .repository import PreferenceRepository,InvalidInterests
from .service import PreferenceService

class InterestsRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    category_ids:list[str]=Field(max_length=100)
    @field_validator('category_ids')
    @classmethod
    def distinct(cls,value):
        if len(value)!=len(set(value)):raise ValueError('Duplicate category IDs are not allowed')
        if any(not v or len(v)>128 for v in value):raise ValueError('Invalid category ID')
        return value

class Interest(BaseModel):
    id:str
    name:str
    taxonomy_version:str
class InterestsResponse(BaseModel):
    interests:list[Interest]
class Candidate(BaseModel):
    video_id:str
    title:str|None
    language:str|None
    duration_seconds:float|None
    orientation:str|None
    category_id:str
    category_name:str
class CandidatesResponse(BaseModel):
    videos:list[Candidate]
    count:int
    limit:int
    strategy:str

def get_service():
    return PreferenceService(PreferenceRepository(),os.getenv('S3_BUCKET_NAME') or os.getenv('AWS_S3_BUCKET'))

def create_router(current_user):
    router=APIRouter(tags=['Preference onboarding'])
    def identity(user=Depends(current_user)):
        try:return UUID(str(user['id']))
        except (ValueError,KeyError,TypeError):raise HTTPException(401,'Invalid authenticated user identity.')
    def invoke(fn):
        try:return fn()
        except InvalidInterests as e:raise HTTPException(422,str(e))
        except HTTPException:raise
        except Exception:raise HTTPException(503,'Preference data is temporarily unavailable.')
    @router.get('/onboarding/interests',response_model=InterestsResponse)
    def interests(service=Depends(get_service)):
        return invoke(service.interests)
    @router.get('/users/me/interests',response_model=InterestsResponse)
    def get_preferences(user_id=Depends(identity),service=Depends(get_service)):
        return invoke(lambda:service.get(user_id))
    @router.put('/users/me/interests',response_model=InterestsResponse)
    def put_preferences(body:InterestsRequest,user_id=Depends(identity),service=Depends(get_service)):
        return invoke(lambda:service.replace(user_id,body.category_ids))
    @router.get('/recommendations/cold-start',response_model=CandidatesResponse)
    def cold_start(limit:Annotated[int,Query(ge=1,le=50)]=50,user_id=Depends(identity),service=Depends(get_service)):
        return invoke(lambda:service.candidates(user_id,limit))
    return router
