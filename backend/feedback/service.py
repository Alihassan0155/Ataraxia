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

    def set_state(self, user_id: UUID, video_id: str, is_liked: bool):
        return self.repository.set_state(
            user_id=user_id,
            video_id=video_id,
            is_liked=is_liked,
        )
