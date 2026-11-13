"""FastAPI routes for authenticated persistent video feedback."""

from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Path, status
from psycopg_pool import PoolTimeout

from .models import (
    FeedbackBatchStateRequest,
    FeedbackBatchStateResponse,
    FeedbackStateRequest,
    FeedbackStateResponse,
)
from .repository import UnknownVideoError
from .service import FeedbackService


def create_router(current_user):
    """Create feedback routes using the application's auth dependency."""

    router = APIRouter(
        prefix="/feedback",
        tags=["Feedback"],
    )

    def get_service():
        return FeedbackService()

    def get_authenticated_user_id(user=Depends(current_user)):
        try:
            return UUID(str(user["id"]))
        except (KeyError, TypeError, ValueError):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authenticated user.",
            )

    def handle_repository_error(error):
        if isinstance(error, UnknownVideoError):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(error),
            )

        if isinstance(error, (psycopg.Error, PoolTimeout)):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Feedback storage is temporarily unavailable.",
            )

        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Feedback storage is temporarily unavailable.",
        )

    @router.post(
        "/batch-state",
        response_model=FeedbackBatchStateResponse,
    )
    def get_batch_state(
        request: FeedbackBatchStateRequest,
        user_id: UUID = Depends(get_authenticated_user_id),
        service: FeedbackService = Depends(get_service),
    ):
        try:
            states = service.get_states(
                user_id=user_id,
                video_ids=request.video_ids,
            )
        except Exception as error:
            handle_repository_error(error)

        return FeedbackBatchStateResponse(states=states)

    @router.put(
        "/videos/{video_id}",
        response_model=FeedbackStateResponse,
    )
    def set_video_state(
        request: FeedbackStateRequest,
        video_id: str = Path(min_length=1, max_length=128),
        user_id: UUID = Depends(get_authenticated_user_id),
        service: FeedbackService = Depends(get_service),
    ):
        try:
            result = service.set_state(
                user_id=user_id,
                video_id=video_id,
                is_liked=request.is_liked,
            )
        except Exception as error:
            handle_repository_error(error)

        return FeedbackStateResponse(**result)

    return router
