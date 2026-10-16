"""Backend-only database configuration. Credentials never enter artifact reports."""
from dataclasses import dataclass, field
import os
from pathlib import Path
import re

TABLES = ('videos', 'video_semantics', 'video_embeddings', 'affect_annotations',
          'video_context', 'processing_runs', 'processing_jobs', 'interest_categories')


@dataclass(frozen=True)
class DatabaseSettings:
    dsn: str = field(repr=False)
    schema: str = 'public'

    @classmethod
    def load(cls, env_file=None, environ=None):
        from dotenv import dotenv_values
        values = {}
        path = Path(env_file) if env_file else Path(__file__).resolve().parents[1]/'.env'
        if path.is_file():
            values.update(dotenv_values(path))
        values.update(os.environ if environ is None else environ)
        dsn = values.get('SUPABASE_DB_URL') or values.get('DATABASE_URL')
        if not dsn:
            raise ValueError('Set SUPABASE_DB_URL (or existing DATABASE_URL) in backend/.env; never pass credentials on the command line')
        if '[YOUR-PASSWORD]' in dsn or '%5BYOUR-PASSWORD%5D' in dsn.upper():
            raise ValueError('Replace the password placeholder privately in backend/.env before connecting; do not send it in chat')
        schema = values.get('ATARAXIA_DB_SCHEMA', 'public')
        if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', schema):
            raise ValueError('Invalid database schema name')
        return cls(dsn=dsn, schema=schema)


def connect(settings):
    import psycopg
    # Supabase direct/pooler PostgreSQL connection; no new project/client provisioned.
    return psycopg.connect(settings.dsn, sslmode='require', connect_timeout=15, autocommit=True,
                          options='-c statement_timeout=30000 -c lock_timeout=5000')
