"""Database migrations for trade ledger system.

Uses schema_version table to track applied migrations.
Each migration runs only once, guarded by version number.
"""

import logging
import sqlite3
import uuid
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def _get_schema_version(conn: sqlite3.Connection) -> int:
    """Get current schema version, creating table if needed."""
    # Check if table exists with correct schema
    try:
        conn.execute("SELECT version, applied_at, description FROM schema_version LIMIT 0")
    except Exception:
        # Table doesn't exist or has wrong schema — recreate
        conn.execute("DROP TABLE IF EXISTS schema_version")
        conn.execute("""
            CREATE TABLE schema_version (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL,
                description TEXT
            )
        """)
        conn.commit()
        return 0

    row = conn.execute("SELECT MAX(version) as v FROM schema_version").fetchone()
    return row["v"] or 0


def _set_schema_version(conn: sqlite3.Connection, version: int, description: str):
    """Record that a migration was applied."""
    conn.execute(
        "INSERT INTO schema_version (version, applied_at, description) VALUES (?, ?, ?)",
        (version, datetime.now(timezone.utc).isoformat(), description),
    )


def _migration_001_trades_table(conn: sqlite3.Connection):
    """Create trades table for trade ledger."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id TEXT PRIMARY KEY,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL CHECK (side IN ('BUY', 'SELL')),
            quantity REAL NOT NULL,
            price REAL NOT NULL,
            amount REAL NOT NULL,
            fee REAL DEFAULT 0,
            currency TEXT DEFAULT 'USD',
            trade_time TEXT NOT NULL,
            source TEXT DEFAULT 'MANUAL',
            reason TEXT,
            note TEXT,
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_trades_time ON trades(trade_time)")
    _set_schema_version(conn, 1, "Create trades table")
    logger.info("Migration 001: Created trades table")


def _migration_002_cash_transactions(conn: sqlite3.Connection):
    """Create cash_transactions table."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cash_transactions (
            id TEXT PRIMARY KEY,
            type TEXT NOT NULL CHECK (type IN ('DEPOSIT', 'WITHDRAW', 'DIVIDEND', 'FEE', 'INTEREST')),
            amount REAL NOT NULL,
            currency TEXT DEFAULT 'USD',
            transaction_time TEXT NOT NULL,
            note TEXT,
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cash_tx_time ON cash_transactions(transaction_time)")
    _set_schema_version(conn, 2, "Create cash_transactions table")
    logger.info("Migration 002: Created cash_transactions table")


def _migration_003_manual_order_plans(conn: sqlite3.Connection):
    """Create manual_order_plans table."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS manual_order_plans (
            id TEXT PRIMARY KEY,
            symbol TEXT NOT NULL,
            source TEXT NOT NULL,
            action TEXT NOT NULL,
            limit_price REAL,
            amount REAL,
            quantity REAL,
            status TEXT NOT NULL DEFAULT 'SUGGESTED',
            filled_quantity REAL DEFAULT 0,
            filled_amount REAL DEFAULT 0,
            reason TEXT,
            note TEXT,
            created_at TEXT NOT NULL,
            expires_at TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_mop_symbol ON manual_order_plans(symbol)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_mop_status ON manual_order_plans(status)")
    _set_schema_version(conn, 3, "Create manual_order_plans table")
    logger.info("Migration 003: Created manual_order_plans table")


def _migration_004_position_snapshots(conn: sqlite3.Connection):
    """Create position_snapshots table."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS position_snapshots (
            id TEXT PRIMARY KEY,
            snapshot_time TEXT NOT NULL,
            symbol TEXT NOT NULL,
            quantity REAL NOT NULL,
            average_cost REAL NOT NULL,
            current_price REAL,
            market_value REAL,
            unrealized_pnl REAL,
            realized_pnl REAL,
            exposure_pct REAL,
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ps_time ON position_snapshots(snapshot_time)")
    _set_schema_version(conn, 4, "Create position_snapshots table")
    logger.info("Migration 004: Created position_snapshots table")


def _migration_005_migrate_trade_log(conn: sqlite3.Connection):
    """Migrate existing trade_log BUY/SELL records into trades table."""
    rows = conn.execute(
        "SELECT * FROM trade_log WHERE action IN ('buy', 'sell') ORDER BY id ASC"
    ).fetchall()

    migrated = 0
    for row in rows:
        trade_id = str(uuid.uuid4())
        symbol = row["ticker"]
        if not symbol:
            continue

        side = "BUY" if row["action"] == "buy" else "SELL"
        quantity = row["shares"] or 0
        price = row["price"] or 0
        amount = round(quantity * price, 2)
        trade_time = row["timestamp"] or datetime.now(timezone.utc).isoformat()
        now = datetime.now(timezone.utc).isoformat()

        conn.execute(
            """INSERT INTO trades (id, symbol, side, quantity, price, amount, fee,
               currency, trade_time, source, reason, note, created_at)
               VALUES (?, ?, ?, ?, ?, ?, 0, 'USD', ?, 'IMPORT', NULL, ?, ?)""",
            (trade_id, symbol.upper(), side, quantity, price, amount,
             trade_time, row["notes"], now),
        )
        migrated += 1

    # Migrate cash adjustments (deposit/withdrawal) from trade_log
    cash_rows = conn.execute(
        "SELECT * FROM trade_log WHERE action IN ('deposit', 'withdrawal') ORDER BY id ASC"
    ).fetchall()

    cash_migrated = 0
    for row in cash_rows:
        tx_id = str(uuid.uuid4())
        cash_before = row["cash_before"] or 0
        cash_after = row["cash_after"] or 0
        amount = cash_after - cash_before
        tx_type = "DEPOSIT" if amount >= 0 else "WITHDRAW"
        tx_time = row["timestamp"] or datetime.now(timezone.utc).isoformat()
        now = datetime.now(timezone.utc).isoformat()

        conn.execute(
            """INSERT INTO cash_transactions (id, type, amount, currency, transaction_time, note, created_at)
               VALUES (?, ?, ?, 'USD', ?, ?, ?)""",
            (tx_id, tx_type, abs(amount), tx_time, row["notes"], now),
        )
        cash_migrated += 1

    _set_schema_version(conn, 5, f"Migrated {migrated} trades and {cash_migrated} cash transactions from trade_log")
    logger.info(f"Migration 005: Migrated {migrated} trades, {cash_migrated} cash transactions from trade_log")


# Ordered list of all migrations
MIGRATIONS = [
    (1, _migration_001_trades_table),
    (2, _migration_002_cash_transactions),
    (3, _migration_003_manual_order_plans),
    (4, _migration_004_position_snapshots),
    (5, _migration_005_migrate_trade_log),
]


def run_migrations(conn: sqlite3.Connection):
    """Run all pending migrations."""
    current_version = _get_schema_version(conn)
    applied = 0

    # Safety check: if schema_version says we're up to date but tables are missing,
    # reset version to force re-run. This handles cases where the DB was partially
    # migrated or the schema_version table was carried over from a different session.
    if current_version >= 3:
        try:
            conn.execute("SELECT COUNT(*) FROM manual_order_plans")
        except Exception:
            logger.warning("schema_version says v%d but manual_order_plans missing, resetting", current_version)
            conn.execute("DELETE FROM schema_version WHERE version >= 3")
            conn.commit()
            current_version = _get_schema_version(conn)

    for version, migration_fn in MIGRATIONS:
        if version > current_version:
            logger.info(f"Running migration {version:03d}...")
            migration_fn(conn)
            applied += 1

    if applied:
        conn.commit()
        logger.info(f"Applied {applied} migration(s). Schema now at version {version}")
    else:
        logger.info(f"Schema up to date at version {current_version}")
