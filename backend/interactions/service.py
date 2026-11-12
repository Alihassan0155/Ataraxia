
"""Service layer for feed interaction ingestion."""

from uuid import UUID

from .repository import InteractionRepository


class InteractionService:
    """Coordinates interaction operations for an authenticated user."""

    def __init__(self, repository=None):
        self.repository = repository or InteractionRepository()

    def register_session(self, user_id: UUID, session_id: UUID) -> UUID:
        """Register a viewing session for the authenticated user."""
        return self.repository.register_session(
            session_id=session_id,
            user_id=user_id,
        )

    def close_session(self, user_id: UUID, session_id: UUID):
        """Close a viewing session owned by the authenticated user."""
        return self.repository.close_session(
            session_id=session_id,
            user_id=user_id,
        )

    def ingest_batch(self, user_id: UUID, events):
        """Persist a batch of events atomically."""
        return self.repository.insert_batch(
            user_id=user_id,
            events=events,
        )
