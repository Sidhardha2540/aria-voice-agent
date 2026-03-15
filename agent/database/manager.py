"""
Single database connection manager.
Owns the connection lifecycle. All repositories share this one connection.
For SQLite: one connection with WAL mode for concurrent reads.
For PostgreSQL: connection pool via asyncpg.
"""
import re
from pathlib import Path

import aiosqlite

from agent.config import settings


def _convert_query_to_postgres(query: str) -> str:
    """Convert SQLite-style ? placeholders to PostgreSQL $1, $2, ..."""
    n = 0
    def repl(_m):
        nonlocal n
        n += 1
        return f"${n}"
    return re.sub(r"\?", repl, query)


class DatabaseManager:
    """
    Usage:
        db = DatabaseManager()
        await db.startup()      # Call once at app start
        conn = db.connection     # All repos use this
        await db.shutdown()     # Call once at app teardown
    """

    def __init__(self) -> None:
        self._conn: aiosqlite.Connection | None = None
        self._pool = None  # For PostgreSQL (asyncpg)

    @property
    def is_postgres(self) -> bool:
        return settings.database_url.startswith("postgresql")

    async def startup(self) -> None:
        if self.is_postgres:
            import asyncpg
            self._pool = await asyncpg.create_pool(
                settings.database_url,
                min_size=5,
                max_size=20,
                command_timeout=10,
            )
            # Run migrations for Postgres (same schema, adapted if needed)
            await self._run_postgres_schema()
        else:
            db_path = settings.database_url.replace("sqlite+aiosqlite:///", "")
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
            self._conn = await aiosqlite.connect(db_path)
            self._conn.row_factory = aiosqlite.Row
            await self._conn.execute("PRAGMA journal_mode=WAL")
            await self._conn.execute("PRAGMA busy_timeout=5000")
            await self._create_tables_sqlite()

    async def _create_tables_sqlite(self) -> None:
        """SQLite only — create tables from migration script."""
        migration_path = Path(__file__).resolve().parent / "migrations" / "001_initial.sql"
        if migration_path.exists():
            sql = migration_path.read_text()
            await self._conn.executescript(sql)
            await self._conn.commit()
        else:
            # Fallback inline schema
            await self._conn.executescript("""
                CREATE TABLE IF NOT EXISTS doctors (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    specialization TEXT NOT NULL,
                    available_days TEXT NOT NULL,
                    slot_duration_minutes INTEGER DEFAULT 30
                );
                CREATE TABLE IF NOT EXISTS appointments (
                    id TEXT PRIMARY KEY,
                    doctor_id INTEGER NOT NULL,
                    patient_name TEXT NOT NULL,
                    patient_phone TEXT NOT NULL,
                    appointment_date TEXT NOT NULL,
                    start_time TEXT NOT NULL,
                    end_time TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'booked',
                    created_at TEXT NOT NULL,
                    notes TEXT DEFAULT '',
                    FOREIGN KEY (doctor_id) REFERENCES doctors(id)
                );
                CREATE TABLE IF NOT EXISTS callers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    phone_number TEXT UNIQUE NOT NULL,
                    name TEXT DEFAULT '',
                    last_call_at TEXT NOT NULL,
                    preferences TEXT DEFAULT '{}',
                    call_count INTEGER DEFAULT 1
                );
                CREATE TABLE IF NOT EXISTS clinic_info (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
            """)
            await self._conn.commit()

    async def _run_postgres_schema(self) -> None:
        """Create tables in PostgreSQL if they don't exist."""
        import asyncpg
        # Use SERIAL and TEXT; no AUTOINCREMENT
        schema = """
        CREATE TABLE IF NOT EXISTS doctors (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            specialization TEXT NOT NULL,
            available_days TEXT NOT NULL,
            slot_duration_minutes INTEGER DEFAULT 30
        );
        CREATE TABLE IF NOT EXISTS appointments (
            id TEXT PRIMARY KEY,
            doctor_id INTEGER NOT NULL,
            patient_name TEXT NOT NULL,
            patient_phone TEXT NOT NULL,
            appointment_date TEXT NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'booked',
            created_at TEXT NOT NULL,
            notes TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS callers (
            id SERIAL PRIMARY KEY,
            phone_number TEXT UNIQUE NOT NULL,
            name TEXT DEFAULT '',
            last_call_at TEXT NOT NULL,
            preferences TEXT DEFAULT '{}',
            call_count INTEGER DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS clinic_info (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        """
        async with self._pool.acquire() as conn:
            for stmt in schema.strip().split(";"):
                stmt = stmt.strip()
                if stmt:
                    await conn.execute(stmt)

    async def shutdown(self) -> None:
        if self._pool:
            await self._pool.close()
            self._pool = None
        if self._conn:
            await self._conn.close()
            self._conn = None

    @property
    def connection(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database not initialized. Call startup() first.")
        return self._conn

    @property
    def pool(self):
        if self._pool is None:
            raise RuntimeError("Database pool not initialized. Call startup() first.")
        return self._pool

    def _row_to_dict(self, row) -> dict:
        """Normalize aiosqlite.Row or asyncpg.Record to dict."""
        if row is None:
            return None
        if hasattr(row, "_mapping"):
            return dict(row._mapping)
        if hasattr(row, "keys"):
            return {k: row[k] for k in row.keys()}
        return dict(row)

    async def execute(self, query: str, *args) -> list[dict]:
        """Unified execute — returns list of rows as dicts."""
        if self.is_postgres:
            q = _convert_query_to_postgres(query)
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(q, *args)
            return [self._row_to_dict(r) for r in rows]
        else:
            async with self._conn.execute(query, args) as cur:
                rows = await cur.fetchall()
            return [self._row_to_dict(r) for r in rows]

    async def execute_one(self, query: str, *args) -> dict | None:
        """Fetch a single row as dict, or None."""
        if self.is_postgres:
            q = _convert_query_to_postgres(query)
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(q, *args)
            return self._row_to_dict(row) if row else None
        else:
            async with self._conn.execute(query, args) as cur:
                row = await cur.fetchone()
            return self._row_to_dict(row) if row else None

    async def execute_write(self, query: str, *args) -> None:
        """Execute INSERT/UPDATE/DELETE and commit."""
        if self.is_postgres:
            q = _convert_query_to_postgres(query)
            async with self._pool.acquire() as conn:
                await conn.execute(q, *args)
        else:
            await self._conn.execute(query, args)
            await self._conn.commit()


# Module-level instance — initialized in main.py startup
db_manager = DatabaseManager()
