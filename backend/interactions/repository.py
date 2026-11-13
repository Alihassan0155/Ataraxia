"""PostgreSQL repository for authenticated feed interaction ingestion."""

from uuid import UUID

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from ..video_data.db_pool import get_connection


class SessionOwnershipError(ValueError):
    """Raised when a session belongs to another user."""


class SessionNotFoundError(ValueError):
    """Raised when a session does not exist or is inaccessible."""


class UnknownVideoError(ValueError):
    """Raised when an event references an unknown video."""


class EventConflictError(ValueError):
    """Raised when an event ID is reused with different data."""


class InteractionRepository:
    def __init__(self, connection_factory=None):
        self.connection_factory = connection_factory or get_connection

    def register_session(self, session_id, user_id):
        session_id = UUID(str(session_id))
        user_id = UUID(str(user_id))

        with self.connection_factory() as conn:
            conn.row_factory = dict_row

            with conn.transaction():
                conn.execute(
                    """
                    INSERT INTO public.sessions (session_id, user_id)
                    VALUES (%s, %s)
                    ON CONFLICT (session_id) DO NOTHING
                    """,
                    (session_id, user_id),
                )

                existing = conn.execute(
                    """
                    SELECT session_id, user_id
                    FROM public.sessions
                    WHERE session_id = %s
                    FOR KEY SHARE
                    """,
                    (session_id,),
                ).fetchone()

                if existing is None:
                    raise RuntimeError(
                        "Session registration could not be verified."
                    )

                if existing["user_id"] != user_id:
                    raise SessionOwnershipError(
                        "This session belongs to another user."
                    )

        return session_id

    def close_session(self, session_id, user_id):
        session_id = UUID(str(session_id))
        user_id = UUID(str(user_id))

        with self.connection_factory() as conn:
            conn.row_factory = dict_row

            with conn.transaction():
                row = conn.execute(
                    """
                    UPDATE public.sessions
                    SET ended_at = COALESCE(ended_at, now())
                    WHERE session_id = %s
                      AND user_id = %s
                    RETURNING session_id, ended_at
                    """,
                    (session_id, user_id),
                ).fetchone()

                if row is None:
                    raise SessionNotFoundError(
                        "Session was not found or is not accessible."
                    )

        return row

    def insert_batch(self, user_id, events):
        """Insert events and synchronize current Like state atomically."""

        user_id = UUID(str(user_id))

        if not events:
            return []

        event_ids = [event.event_id for event in events]
        session_ids = sorted({event.session_id for event in events})
        video_ids = sorted({event.video_id for event in events})

        with self.connection_factory() as conn:
            conn.row_factory = dict_row

            with conn.transaction():
                session_rows = conn.execute(
                    """
                    SELECT session_id, user_id
                    FROM public.sessions
                    WHERE session_id = ANY(%s::uuid[])
                    FOR KEY SHARE
                    """,
                    (session_ids,),
                ).fetchall()

                owned_sessions = {
                    row["session_id"]
                    for row in session_rows
                    if row["user_id"] == user_id
                }

                if owned_sessions != set(session_ids):
                    raise SessionNotFoundError(
                        "One or more sessions were not found or are not accessible."
                    )

                video_rows = conn.execute(
                    """
                    SELECT video_id
                    FROM public.videos
                    WHERE video_id = ANY(%s::text[])
                    """,
                    (video_ids,),
                ).fetchall()

                existing_videos = {
                    row["video_id"] for row in video_rows
                }

                if existing_videos != set(video_ids):
                    raise UnknownVideoError(
                        "One or more submitted videos do not exist."
                    )

                newly_inserted_feedback_videos = set()

                for event in events:
                    inserted = conn.execute(
                        """
                        INSERT INTO public.interactions (
                            interaction_id,
                            session_id,
                            video_id,
                            event_type,
                            occurred_at,
                            watch_duration_ms,
                            metadata
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (interaction_id) DO NOTHING
                        RETURNING interaction_id
                        """,
                        (
                            event.event_id,
                            event.session_id,
                            event.video_id,
                            event.event_type,
                            event.occurred_at,
                            event.watch_duration_ms,
                            Jsonb(event.metadata),
                        ),
                    ).fetchone()

                    if inserted is None:
                        existing = conn.execute(
                            """
                            SELECT
                                session_id,
                                video_id,
                                event_type,
                                occurred_at,
                                watch_duration_ms,
                                metadata
                            FROM public.interactions
                            WHERE interaction_id = %s
                            """,
                            (event.event_id,),
                        ).fetchone()

                        if (
                            existing is None
                            or not self._same_event(existing, event)
                        ):
                            raise EventConflictError(
                                "An event ID was reused with different event data."
                            )
                    elif event.event_type in {"like", "unlike"}:
                        newly_inserted_feedback_videos.add(event.video_id)

                # Serialize feedback-state reconstruction per user/video.
                # Sorting gives batches a consistent lock acquisition order.
                for video_id in sorted(newly_inserted_feedback_videos):
                    lock_key = f"{user_id}:{video_id}"

                    conn.execute(
                        """
                        SELECT pg_advisory_xact_lock(
                            hashtextextended(%s, 0)
                        )
                        """,
                        (lock_key,),
                    )

                    latest_event = conn.execute(
                        """
                        SELECT i.event_type
                        FROM public.interactions AS i
                        INNER JOIN public.sessions AS s
                            ON s.session_id = i.session_id
                        WHERE s.user_id = %s
                          AND i.video_id = %s
                          AND i.event_type IN ('like', 'unlike')
                        ORDER BY
                            i.occurred_at DESC,
                            i.received_at DESC,
                            i.interaction_id DESC
                        LIMIT 1
                        """,
                        (user_id, video_id),
                    ).fetchone()

                    if latest_event is None:
                        raise RuntimeError(
                            "Latest feedback event could not be verified."
                        )

                    is_liked = latest_event["event_type"] == "like"

                    feedback_row = conn.execute(
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
                        RETURNING video_id, is_liked
                        """,
                        (user_id, video_id, is_liked),
                    ).fetchone()

                    if feedback_row is None:
                        raise RuntimeError(
                            "Current feedback state could not be verified."
                        )

        return event_ids

    @staticmethod
    def _same_event(existing, event):
        return (
            existing["session_id"] == event.session_id
            and existing["video_id"] == event.video_id
            and existing["event_type"] == event.event_type
            and existing["occurred_at"] == event.occurred_at
            and existing["watch_duration_ms"] == event.watch_duration_ms
            and existing["metadata"] == event.metadata
        )
