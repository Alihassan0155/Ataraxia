"""Service layer for persistent video feedback."""

from uuid import UUID

from .repository import FeedbackRepository


class FeedbackService:
    """Coordinates feedback operations for an authenticated user."""

    def __init__(self, repository=None):
        self.repository = repository or FeedbackRepository()

    def get_states(self, user_id: UUID, video_ids):
        return self.repository.get_states(
            user_id=user_id,
            video_ids=video_ids,
        )
