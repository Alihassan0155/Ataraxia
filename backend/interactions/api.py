
"""FastAPI routes for feed interaction ingestion."""

from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException, status
from psycopg_pool import PoolTimeout

from .models import (
    InteractionBatchRequest,
    InteractionBatchResponse,
    SessionCloseResponse,
    SessionRegistrationRequest,
    SessionRegistrationResponse,
)
from .repository import (
    EventConflictError,
    SessionNotFoundError,
    SessionOwnershipError,
    UnknownVideoError,
)
from .service import InteractionService


def create_router(current_user):
    """Create interaction routes using the application's auth dependency."""

    router = APIRouter(
        prefix="/interactions",
        tags=["Interactions"],
    )

    def get_service():
        return InteractionService()

    def get_authenticated_user_id(user=Depends(current_user)):
        try:
            return UUID(str(user["id"]))
        except (KeyError, TypeError, ValueError):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authenticated user.",
            )

    def handle_repository_error(error):
        if isinstance(error, SessionOwnershipError):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(error),
            )

        if isinstance(error, SessionNotFoundError):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(error),
            )

        if isinstance(error, UnknownVideoError):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(error),
            )

        if isinstance(error, EventConflictError):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(error),
            )

        if isinstance(error, (psycopg.Error, PoolTimeout)):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Interaction storage is temporarily unavailable.",
            )

        # Do not expose unexpected internal errors or connection details.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Interaction storage is temporarily unavailable.",
        )

    @router.post(
        "/sessions",
        response_model=SessionRegistrationResponse,
        status_code=status.HTTP_200_OK,
    )
    def register_session(
        request: SessionRegistrationRequest,
        user_id: UUID = Depends(get_authenticated_user_id),
        service: InteractionService = Depends(get_service),
    ):
        try:
            registered_session_id = service.register_session(
                user_id=user_id,
                session_id=request.session_id,
            )
        except Exception as error:
            handle_repository_error(error)

        return SessionRegistrationResponse(
            session_id=registered_session_id,
            registered=True,
        )

    @router.post(
        "/sessions/{session_id}/close",
        response_model=SessionCloseResponse,
    )
    def close_session(
        session_id: UUID,
        user_id: UUID = Depends(get_authenticated_user_id),
        service: InteractionService = Depends(get_service),
    ):
        try:
            result = service.close_session(
                user_id=user_id,
                session_id=session_id,
            )
        except Exception as error:
            handle_repository_error(error)

        return SessionCloseResponse(
            session_id=result["session_id"],
            ended_at=result["ended_at"],
        )

    @router.post(
        "/batch",
        response_model=InteractionBatchResponse,
    )
    def ingest_batch(
        request: InteractionBatchRequest,
        user_id: UUID = Depends(get_authenticated_user_id),
        service: InteractionService = Depends(get_service),
    ):
        try:
            accepted_event_ids = service.ingest_batch(
                user_id=user_id,
                events=request.events,
            )
        except Exception as error:
            handle_repository_error(error)

        return InteractionBatchResponse(
            accepted_event_ids=accepted_event_ids,
            accepted_count=len(accepted_event_ids),
        )

    return router
