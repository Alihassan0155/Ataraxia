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

    def set_state(self, user_id, video_id, is_liked):
        """Insert or update a user's current feedback state idempotently."""

        user_id = UUID(str(user_id))

        if (
            not isinstance(video_id, str)
            or not video_id.strip()
            or video_id != video_id.strip()
            or len(video_id) > 128
        ):
            raise ValueError("Invalid video ID.")

        with self.connection_factory() as conn:
            conn.row_factory = dict_row

            with conn.transaction():
                video = conn.execute(
                    """
                    SELECT video_id
                    FROM public.videos
                    WHERE video_id = %s
                    """,
                    (video_id,),
                ).fetchone()

                if video is None:
                    raise UnknownVideoError(
                        "The requested video does not exist."
                    )

                row = conn.execute(
                    """
                    INSERT INTO public.user_video_feedback (
                        user_id,
                        video_id,
                        is_liked
                    )
                    VALUES (%s, %s, %s)
                    ON CONFLICT (user_id, video_id)
                    DO UPDATE SET
                        is_liked = EXCLUDED.is_liked,
                        updated_at = CASE
                            WHEN public.user_video_feedback.is_liked
                                 IS DISTINCT FROM EXCLUDED.is_liked
                            THEN now()
                            ELSE public.user_video_feedback.updated_at
                        END
                    RETURNING
                        video_id,
                        is_liked,
                        created_at,
                        updated_at
                    """,
                    (user_id, video_id, is_liked),
                ).fetchone()

                if row is None:
                    raise RuntimeError(
                        "Feedback state could not be verified."
                    )

        return {
            "video_id": row["video_id"],
            "is_liked": row["is_liked"],
            "has_feedback": True,
        }
