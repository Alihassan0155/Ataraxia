"""Prevent historical replay once physical one-row-per-video storage is active."""
from pathlib import Path


MARKER = Path(__file__).resolve().parents[1] / 'reports/physical_dedup_execution_20261104/committed.json'


def require_legacy_disabled(conn=None, schema='public'):
    """Fail before legacy writes; also recognize the schema on another checkout."""
    active = MARKER.exists()
    if conn is not None:
        active = active or bool(conn.execute(
            'SELECT 1 FROM pg_indexes WHERE schemaname=%s AND indexname=%s',
            (schema, 'video_context_one_video_physical_v1')).fetchone())
    if active:
        raise ValueError('Physical 1:1 storage is active; historical import/replacement is disabled. Use the canonical writer.')
