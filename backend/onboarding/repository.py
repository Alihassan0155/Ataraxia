
"""Small PostgreSQL repository; no video data is written by this module."""

from uuid import UUID

from psycopg.rows import dict_row

from ..video_data.db_pool import get_connection


class InvalidInterests(ValueError):
    pass


class PreferenceRepository:
    def __init__(self, connection_factory=None):
        self.connection_factory = connection_factory or get_connection

    @staticmethod
    def categories(conn):
        return conn.execute(
            """
            SELECT id, name, taxonomy_version
            FROM public.interest_categories
            WHERE is_onboarding
              AND lower(name) <> 'unknown'
            ORDER BY name, id
            """
        ).fetchall()

    def interests(self):
        with self.connection_factory() as conn:
            conn.row_factory = dict_row
            return self.categories(conn)

    def preferences(self, user_id):
        user_id = UUID(str(user_id))

        with self.connection_factory() as conn:
            conn.row_factory = dict_row

            with conn.transaction():
                conn.execute("SET TRANSACTION READ ONLY")
                return self.selected(conn, user_id)

    @staticmethod
    def selected(conn, user_id):
        return conn.execute(
            """
            SELECT c.id, c.name, c.taxonomy_version
            FROM public.user_interest_preferences p
            JOIN public.interest_categories c
              ON c.id = p.category_id
            WHERE p.user_id = %s
              AND c.is_onboarding
              AND lower(c.name) <> 'unknown'
            ORDER BY c.name, c.id
            """,
            (user_id,),
        ).fetchall()

    def replace(self, user_id, ids):
        user_id = UUID(str(user_id))

        if len(ids) != len(set(ids)):
            raise InvalidInterests("Duplicate category IDs are not allowed.")

        with self.connection_factory() as conn:
            conn.row_factory = dict_row

            with conn.transaction():
                # Serialize replacements even when a user currently has zero rows.
                conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (str(user_id),),)
                allowed = {row["id"] for row in self.categories(conn)}

                if set(ids) - allowed:
                    raise InvalidInterests("One or more interests are invalid or not selectable.")

                current = {
                    row["category_id"]
                    for row in conn.execute(
                        """
                        SELECT category_id
                        FROM public.user_interest_preferences
                        WHERE user_id = %s
                        FOR UPDATE
                        """,
                        (user_id,),
                    ).fetchall()
                }

                if current != set(ids):
                    conn.execute(
                        """
                        DELETE FROM public.user_interest_preferences
                        WHERE user_id = %s
                          AND NOT (category_id = ANY(%s::text[]))
                        """,
                        (user_id, ids),
                    )

                    for category_id in sorted(set(ids) - current):
                        conn.execute(
                            """
                            INSERT INTO public.user_interest_preferences
                                (user_id, category_id)
                            VALUES (%s, %s)
                            """,
                            (user_id, category_id),
                        )

                return self.selected(conn, user_id)

    def candidate_pool(self, user_id):
        user_id = UUID(str(user_id))

        with self.connection_factory() as conn:
            conn.row_factory = dict_row

            with conn.transaction():
                conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                selected = self.selected(conn, user_id)

                if not selected:
                    return selected, []

                # payload.category remains the canonical source metadata mapping.
                # No semantic/embedding join and no Qwen category fallback.
                videos = conn.execute(
                    """
                    SELECT v.video_id, v.title, v.language, v.duration_seconds, v.orientation, v.media_uri, v.availability,
                        c.id AS category_id, c.name AS category_name
                    FROM public.videos v
                    JOIN public.interest_categories c
                      ON c.name = v.payload->>'category'
                    WHERE c.id = ANY(%s::text[])
                      AND c.is_onboarding
                      AND lower(c.name) <> 'unknown'
                      AND v.availability = 's3_verified'
                      AND v.media_sha256 ~ '^[0-9a-fA-F]{64}$'
                    ORDER BY v.video_id, c.id
                    """,
                    ([row["id"] for row in selected],),
                ).fetchall()

                return selected, videos
