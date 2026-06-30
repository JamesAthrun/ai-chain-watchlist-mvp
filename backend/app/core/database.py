"""SQLite database for portfolio management."""

import json
import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent.parent / "data"
DB_PATH = DATA_DIR / "portfolio.db"
CONFIG_DIR = Path(__file__).parent.parent / "config"


def get_db() -> sqlite3.Connection:
    """Get a database connection with row factory."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Create tables if they don't exist and seed from portfolio.json if empty."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = get_db()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS portfolio_meta (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                account_value REAL NOT NULL DEFAULT 0,
                cash REAL NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT NOT NULL,
                shares REAL NOT NULL DEFAULT 0,
                avg_cost REAL NOT NULL DEFAULT 0,
                bucket TEXT,
                intent TEXT,
                UNIQUE(ticker)
            );

            CREATE TABLE IF NOT EXISTS trade_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL DEFAULT (datetime('now')),
                action TEXT NOT NULL CHECK (action IN ('buy', 'sell', 'set_portfolio')),
                ticker TEXT,
                shares REAL,
                price REAL,
                cash_before REAL,
                cash_after REAL,
                shares_before REAL,
                shares_after REAL,
                avg_cost_before REAL,
                avg_cost_after REAL,
                notes TEXT
            );
        """)

        # Seed from portfolio.json if portfolio_meta is empty
        row = conn.execute("SELECT COUNT(*) as cnt FROM portfolio_meta").fetchone()
        if row["cnt"] == 0:
            _seed_from_json(conn)

        conn.commit()

        # Run trade ledger migrations
        from app.core.migrations import run_migrations
        run_migrations(conn)

        logger.info(f"Database initialized at {DB_PATH}")
    finally:
        conn.close()


def _seed_from_json(conn: sqlite3.Connection):
    """Seed database from portfolio.json."""
    json_path = CONFIG_DIR / "portfolio.json"
    if not json_path.exists():
        # Insert default
        conn.execute(
            "INSERT INTO portfolio_meta (id, account_value, cash) VALUES (1, 0, 0)"
        )
        return

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    account_value = data.get("account_value", 0)
    cash = data.get("cash", 0)

    conn.execute(
        "INSERT INTO portfolio_meta (id, account_value, cash) VALUES (1, ?, ?)",
        (account_value, cash),
    )

    for pos in data.get("positions", []):
        conn.execute(
            "INSERT OR IGNORE INTO positions (ticker, shares, avg_cost, bucket, intent) VALUES (?, ?, ?, ?, ?)",
            (pos.get("ticker"), pos.get("shares", 0), pos.get("avg_cost", 0),
             pos.get("bucket"), pos.get("intent")),
        )

    conn.execute(
        "INSERT INTO trade_log (action, notes, cash_after) VALUES ('set_portfolio', 'Seeded from portfolio.json', ?)",
        (cash,),
    )

    logger.info(f"Seeded database from {json_path}")
