CREATE TABLE IF NOT EXISTS regime_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL NOT NULL,
    regime TEXT NOT NULL,
    bdi_value REAL, vix_value REAL, yield_curve REAL, dxy REAL,
    notes TEXT
);
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL NOT NULL,
    worker TEXT NOT NULL,
    symbol TEXT NOT NULL,
    direction TEXT NOT NULL,
    confidence REAL,
    suggested_size_pct REAL,
    regime_tags TEXT,
    ttl_seconds INTEGER,
    rationale TEXT,
    acted_on INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL NOT NULL,
    signal_id INTEGER REFERENCES signals(id),
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    quantity REAL, price REAL, status TEXT,
    worker TEXT, mode TEXT, pnl REAL
);
CREATE TABLE IF NOT EXISTS portfolio_state (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL NOT NULL,
    total_value REAL, cash_pct REAL,
    drawdown_pct REAL, regime TEXT, allocations TEXT
);
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
