"""Shared PostgreSQL connection pool for backend requests."""

from psycopg_pool import ConnectionPool

from .config import DatabaseSettings

_pool = None


def open_pool():
    """Create and open the shared pool once during application startup."""
    global _pool

    if _pool is None:
        settings = DatabaseSettings.load()
        _pool = ConnectionPool(
            conninfo=settings.dsn,
            min_size=1,
            max_size=5,
            timeout=15,
            kwargs={
                "sslmode": "require",
                "autocommit": True,
                "options": "-c statement_timeout=30000 -c lock_timeout=5000",
            },
            open=False,
        )
        try:
            _pool.open(wait=True, timeout=15)
        except Exception:
            _pool.close()
            _pool = None
            raise

    return _pool


def get_connection():
    """Return a connection context manager backed by the shared pool."""
    if _pool is None:
        raise RuntimeError("Database connection pool has not been opened.")
    return _pool.connection()


def close_pool():
    """Close the shared pool during application shutdown."""
    global _pool

    if _pool is not None:
        _pool.close()
        _pool = None
