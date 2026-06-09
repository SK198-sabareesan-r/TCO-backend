"""
utils/db.py
-----------
PostgreSQL RDS connection pool and query helpers for AWS instance spec lookups.
"""

import logging
from typing import Any, Optional
import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor
from config.secrets import get_secret

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Connection Pool (shared across all agents)
# ─────────────────────────────────────────────────────────────────────────────
_pool: Optional[pool.SimpleConnectionPool] = None


def get_pool() -> pool.SimpleConnectionPool:
    global _pool
    if _pool is None:
        _pool = pool.SimpleConnectionPool(
            minconn=1,
            maxconn=10,
            host=get_secret("DB_HOST", "localhost"),
            port=int(get_secret("DB_PORT", "5432")),
            dbname=get_secret("DB_NAME", "aws_pricing"),
            user=get_secret("DB_USER", "postgres"),
            password=get_secret("DB_PASSWORD", ""),
        )
        logger.info("PostgreSQL connection pool created.")
    return _pool


def execute_query(sql: str, params: tuple = ()) -> list[dict]:
    """
    Execute a SELECT query and return rows as list of dicts.
    Automatically returns connection to pool after use.

    Applies a universal NA-safety rewrite before execution:
    Any CAST("vcpu" AS INTEGER) or CAST(REPLACE("memory",...) AS FLOAT) in the
    SQL will silently fail on rows where the column contains 'NA' or NULL.
    We inject a WHERE filter that strips those rows out before any CAST happens,
    regardless of where in the WHERE clause the CAST appears.
    """
    conn = None
    try:
        # ── Universal NA-safety rewrite ────────────────────────────────────────
        # Inject vcpu/memory NA guards if the SQL casts those columns and the
        # guards are not already present.  Works regardless of exact WHERE structure.
        if 'CAST("vcpu"' in sql and '"vcpu" != \'NA\'' not in sql:
            if 'WHERE' in sql.upper():
                # Insert right after the first WHERE keyword
                sql = sql.replace('WHERE ', 'WHERE "vcpu" IS NOT NULL AND "vcpu" != \'NA\' AND ', 1)
            logger.debug("✅ [db] Injected vcpu NA guard")

        if 'CAST(REPLACE("memory"' in sql and '"memory" != \'NA\'' not in sql:
            if 'WHERE' in sql.upper():
                sql = sql.replace('WHERE ', 'WHERE "memory" IS NOT NULL AND "memory" != \'NA\' AND ', 1)
            logger.debug("✅ [db] Injected memory NA guard")
        # ──────────────────────────────────────────────────────────────────────

        conn = get_pool().getconn()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
            return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"DB query error: {e}\nSQL: {sql}\nParams: {params}")
        raise
    finally:
        if conn:
            get_pool().putconn(conn)


def test_connection() -> bool:
    """Ping the DB – returns True if reachable."""
    try:
        rows = execute_query("SELECT 1 AS ok")
        return rows[0]["ok"] == 1
    except Exception:
        return False