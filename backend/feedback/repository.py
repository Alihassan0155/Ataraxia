"""PostgreSQL repository for persistent per-user video feedback."""

from uuid import UUID

from psycopg.rows import dict_row

from ..video_data.db_pool import get_connection


class UnknownVideoError(ValueError):
    """Raised when feedback references an unknown video."""


class FeedbackRepository:
    def __init__(self, connection_factory=None):
        self.connection_factory = connection_factory or get_connection

    def get_states(self, user_id, video_ids):
        """Return current feedback states, preserving requested video order."""

        user_id = UUID(str(user_id))

        if not video_ids:
            return []

        with self.connection_factory() as conn:
            conn.row_factory = dict_row

            video_rows = conn.execute(
                """
                SELECT video_id
                FROM public.videos
                WHERE video_id = ANY(%s::text[])
                """,
                (video_ids,),
            ).fetchall()

            existing_video_ids = {
                row["video_id"] for row in video_rows
            }

            if existing_video_ids != set(video_ids):
                raise UnknownVideoError(
                    "One or more requested videos do not exist."
                )

            feedback_rows = conn.execute(
                """
                SELECT video_id, is_liked
                FROM public.user_video_feedback
                WHERE user_id = %s
                  AND video_id = ANY(%s::text[])
                """,
                (user_id, video_ids),
            ).fetchall()

        feedback_by_video = {
            row["video_id"]: row["is_liked"]
            for row in feedback_rows
        }

        states = []

        for video_id in video_ids:
            has_feedback = video_id in feedback_by_video

            states.append({
                "video_id": video_id,
                "is_liked": (
                    feedback_by_video[video_id]
                    if has_feedback
                    else False
                ),
                "has_feedback": has_feedback,
            })

        return states
