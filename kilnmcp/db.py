"""SQLite storage. Every batch row carries synthetic=1."""
from __future__ import annotations
import sqlite3, os, time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS batches(id TEXT PRIMARY KEY, start_ts REAL, end_ts REAL, feedstock TEXT,
  input_mass_kg REAL, output_mass_kg REAL, seed INTEGER, faults TEXT, synthetic INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS readings(id INTEGER PRIMARY KEY, batch_id TEXT, ts REAL, sensor TEXT, value REAL,
  source TEXT CHECK(source IN ('sim','uart')));
CREATE INDEX IF NOT EXISTS ix_read ON readings(batch_id, sensor, ts);
CREATE TABLE IF NOT EXISTS anomalies(id INTEGER PRIMARY KEY, batch_id TEXT, ts REAL, end_ts REAL, sensor TEXT,
  rule TEXT, value REAL, threshold REAL, severity TEXT, samples INTEGER);
CREATE TABLE IF NOT EXISTS diagnoses(id INTEGER PRIMARY KEY, anomaly_id INTEGER, model TEXT, explanation TEXT,
  suggested_action TEXT, created_at REAL);
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, batch_id TEXT, ts REAL, kind TEXT, note TEXT);
CREATE TABLE IF NOT EXISTS reports(id INTEGER PRIMARY KEY, batch_id TEXT, path TEXT, model TEXT, created_at REAL,
  status TEXT NOT NULL DEFAULT 'DRAFT_NOT_CERTIFIED');
"""

def default_path() -> str:
    return os.environ.get("KILNMCP_DB", str(Path.cwd() / "data" / "kiln.db"))

def connect(path: str | None = None) -> sqlite3.Connection:
    path = path or default_path()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=30)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con

def now() -> float:
    return time.time()
