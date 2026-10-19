"""Small PostgreSQL repository; no video data is written by this module."""
from uuid import UUID
from psycopg.rows import dict_row
from ..video_data.config import DatabaseSettings,connect

class InvalidInterests(ValueError):pass

class PreferenceRepository:
    def __init__(self,connection_factory=None):
        self.connection_factory=connection_factory or (lambda:connect(DatabaseSettings.load()))

    @staticmethod
    def categories(conn):
        return conn.execute("SELECT id,name,taxonomy_version FROM public.interest_categories WHERE is_onboarding AND lower(name)<>'unknown' ORDER BY name,id").fetchall()

    def interests(self):
        with self.connection_factory() as c:
            c.row_factory=dict_row
            with c.transaction():
                c.execute('SET TRANSACTION READ ONLY')
                return self.categories(c)

    def preferences(self,user_id):
        user_id=UUID(str(user_id))
        with self.connection_factory() as c:
            c.row_factory=dict_row
            with c.transaction():
                c.execute('SET TRANSACTION READ ONLY')
                return self.selected(c,user_id)

    @staticmethod
    def selected(c,user_id):
        return c.execute("""SELECT c.id,c.name,c.taxonomy_version FROM public.user_interest_preferences p
          JOIN public.interest_categories c ON c.id=p.category_id
          WHERE p.user_id=%s AND c.is_onboarding AND lower(c.name)<>'unknown' ORDER BY c.name,c.id""",(user_id,)).fetchall()

    def replace(self,user_id,ids):
        user_id=UUID(str(user_id))
        if len(ids)!=len(set(ids)):raise InvalidInterests('Duplicate category IDs are not allowed.')
        with self.connection_factory() as c:
            c.row_factory=dict_row
            with c.transaction():
                # Serialize replacements even when a user currently has zero rows.
                c.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',(str(user_id),))
                allowed={r['id'] for r in self.categories(c)}
                if set(ids)-allowed:raise InvalidInterests('One or more interests are invalid or not selectable.')
                current={r['category_id'] for r in c.execute('SELECT category_id FROM public.user_interest_preferences WHERE user_id=%s FOR UPDATE',(user_id,))}
                if current!=set(ids):
                    c.execute('DELETE FROM public.user_interest_preferences WHERE user_id=%s AND NOT(category_id=ANY(%s::text[]))',(user_id,ids))
                    for category in sorted(set(ids)-current):
                        c.execute('INSERT INTO public.user_interest_preferences(user_id,category_id) VALUES(%s,%s)',(user_id,category))
                return self.selected(c,user_id)

    def candidate_pool(self,user_id):
        user_id=UUID(str(user_id))
        with self.connection_factory() as c:
            c.row_factory=dict_row
            with c.transaction():
                c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
                selected=self.selected(c,user_id)
                if not selected:return selected,[]
                # payload.category is the existing canonical SOURCE metadata mapping.
                # No semantic/embedding join and no Qwen category fallback.
                videos=c.execute("""SELECT v.video_id,v.title,v.language,v.duration_seconds,v.orientation,
                    v.media_uri,v.availability,c.id AS category_id,c.name AS category_name
                    FROM public.videos v JOIN public.interest_categories c ON c.name=v.payload->>'category'
                    WHERE c.id=ANY(%s::text[]) AND c.is_onboarding AND lower(c.name)<>'unknown'
                      AND v.availability='s3_verified' AND v.media_sha256 ~ '^[0-9a-fA-F]{64}$'
                    ORDER BY v.video_id,c.id""",([r['id'] for r in selected],)).fetchall()
                return selected,videos
