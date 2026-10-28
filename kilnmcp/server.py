"""KilnMCP FastMCP server. stdio (default) or Streamable HTTP. All data SYNTHETIC."""
from __future__ import annotations
import argparse, json, os
from pathlib import Path
import yaml
from mcp.server.fastmcp import FastMCP
from . import db, SENSORS, SYNTHETIC_BANNER

THRESH_PATH = os.environ.get("KILNMCP_THRESHOLDS", str(Path(__file__).resolve().parent.parent / "config" / "thresholds.yaml"))

mcp = FastMCP("kiln", log_level="WARNING", instructions=f"Biochar kiln telemetry. {SYNTHETIC_BANNER}.")

def _con():
    return db.connect()

def _wrap(d: dict) -> dict:
    return {"synthetic": True, "banner": SYNTHETIC_BANNER, **d}

def _latest_batch(con) -> str | None:
    r = con.execute("SELECT id FROM batches ORDER BY start_ts DESC, rowid DESC LIMIT 1").fetchone()
    return r["id"] if r else None

def _check_sensor(sensor: str):
    if sensor not in SENSORS:
        raise ValueError(f"unknown sensor {sensor!r}; expected one of {SENSORS}")

@mcp.tool()
def get_latest(sensor: str, batch_id: str | None = None) -> dict:
    """Latest reading of one sensor (temp_c, o2_pct, moisture_pct, mass_kg)."""
    _check_sensor(sensor)
    con = _con(); batch_id = batch_id or _latest_batch(con)
    r = con.execute("SELECT ts,value,source FROM readings WHERE batch_id=? AND sensor=? ORDER BY ts DESC LIMIT 1",
                    (batch_id, sensor)).fetchone()
    return _wrap({"batch_id": batch_id, "sensor": sensor, **(dict(r) if r else {"value": None})})

@mcp.tool()
def get_window(sensor: str, minutes: float = 10, batch_id: str | None = None, end_ts: float | None = None) -> dict:
    """Readings of one sensor over the last `minutes` (ending at end_ts, default latest) plus summary stats."""
    _check_sensor(sensor)
    con = _con(); batch_id = batch_id or _latest_batch(con)
    if end_ts is None:
        r = con.execute("SELECT MAX(ts) m FROM readings WHERE batch_id=?", (batch_id,)).fetchone()
        end_ts = r["m"] or 0
    rows = con.execute("SELECT ts,value FROM readings WHERE batch_id=? AND sensor=? AND ts>? AND ts<=? ORDER BY ts",
                       (batch_id, sensor, end_ts - minutes * 60, end_ts)).fetchall()
    vals = [x["value"] for x in rows]
    stats = {}
    if vals:
        mu = sum(vals) / len(vals)
        stats = {"n": len(vals), "min": min(vals), "max": max(vals), "mean": round(mu, 3),
                 "std": round((sum((v - mu) ** 2 for v in vals) / len(vals)) ** 0.5, 3)}
    return _wrap({"batch_id": batch_id, "sensor": sensor, "end_ts": end_ts, "minutes": minutes,
                  "stats": stats, "readings": [[x["ts"], x["value"]] for x in rows]})

def _batch(con, batch_id: str) -> dict:
    b = con.execute("SELECT * FROM batches WHERE id=?", (batch_id,)).fetchone()
    if not b:
        raise ValueError(f"no batch {batch_id!r}")
    d = dict(b); d["faults_injected"] = json.loads(d.pop("faults") or "[]"); d["synthetic"] = bool(d["synthetic"])
    agg = con.execute("SELECT sensor, COUNT(*) n, MIN(value) mn, MAX(value) mx, AVG(value) av FROM readings "
                      "WHERE batch_id=? GROUP BY sensor", (batch_id,)).fetchall()
    d["sensor_summary"] = {a["sensor"]: {"n": a["n"], "min": a["mn"], "max": a["mx"], "mean": round(a["av"], 3)} for a in agg}
    d["sources"] = [r[0] for r in con.execute("SELECT DISTINCT source FROM readings WHERE batch_id=?", (batch_id,))]
    d["duration_min"] = round((d["end_ts"] - d["start_ts"]) / 60, 2)
    return d

@mcp.tool()
def get_batch(batch_id: str) -> dict:
    """Batch metadata + per-sensor summary (numbers straight from SQL)."""
    return _wrap(_batch(_con(), batch_id))

@mcp.tool()
def list_batches() -> dict:
    """All batch ids."""
    return _wrap({"batches": [dict(r) for r in _con().execute("SELECT id,start_ts,feedstock FROM batches")]})

@mcp.tool()
def list_anomalies(batch_id: str) -> dict:
    """Anomalies recorded for a batch, with any diagnoses attached."""
    con = _con(); out = []
    for a in con.execute("SELECT * FROM anomalies WHERE batch_id=? ORDER BY ts", (batch_id,)):
        d = dict(a)
        d["diagnoses"] = [dict(x) for x in con.execute("SELECT model,explanation,suggested_action FROM diagnoses WHERE anomaly_id=?", (a["id"],))]
        out.append(d)
    return _wrap({"batch_id": batch_id, "anomalies": out})

@mcp.tool()
def record_anomaly(batch_id: str, ts: float, end_ts: float, sensor: str, rule: str, value: float,
                   threshold: float, severity: str, samples: int = 1) -> dict:
    """(Monitor agent) store a detected anomaly event."""
    con = _con()
    cur = con.execute("INSERT INTO anomalies(batch_id,ts,end_ts,sensor,rule,value,threshold,severity,samples) VALUES(?,?,?,?,?,?,?,?,?)",
                      (batch_id, ts, end_ts, sensor, rule, value, threshold, severity, samples))
    con.commit()
    return _wrap({"anomaly_id": cur.lastrowid})

@mcp.tool()
def save_diagnosis(anomaly_id: int, model: str, explanation: str, suggested_action: str) -> dict:
    """(Diagnosis agent) attach an LLM explanation to an anomaly."""
    con = _con()
    cur = con.execute("INSERT INTO diagnoses(anomaly_id,model,explanation,suggested_action,created_at) VALUES(?,?,?,?,?)",
                      (anomaly_id, model, explanation, suggested_action, db.now()))
    con.commit()
    return _wrap({"diagnosis_id": cur.lastrowid})

@mcp.tool()
def save_report(batch_id: str, path: str, model: str) -> dict:
    """(Reporting agent) register a report file. Status is always DRAFT_NOT_CERTIFIED."""
    con = _con()
    cur = con.execute("INSERT INTO reports(batch_id,path,model,created_at) VALUES(?,?,?,?)", (batch_id, path, model, db.now()))
    con.commit()
    return _wrap({"report_id": cur.lastrowid, "status": "DRAFT_NOT_CERTIFIED"})

@mcp.tool()
def log_event(batch_id: str, kind: str, note: str) -> dict:
    """Append a free-form operator/agent event to the batch log."""
    con = _con()
    cur = con.execute("INSERT INTO events(batch_id,ts,kind,note) VALUES(?,?,?,?)", (batch_id, db.now(), kind, note))
    con.commit()
    return _wrap({"event_id": cur.lastrowid})

@mcp.resource("kiln://batches/{batch_id}")
def batch_resource(batch_id: str) -> str:
    """Batch summary as JSON."""
    return json.dumps(_wrap(_batch(_con(), batch_id)), indent=2)

@mcp.resource("kiln://thresholds")
def thresholds_resource() -> str:
    """Monitor thresholds YAML (edit config/thresholds.yaml)."""
    return Path(THRESH_PATH).read_text(encoding="utf-8")

@mcp.resource("kiln://schema")
def schema_resource() -> str:
    """SQLite schema."""
    return f"-- {SYNTHETIC_BANNER}\n{db.SCHEMA}"

@mcp.prompt()
def diagnose_anomaly(batch_id: str, anomaly_json: str, context_json: str) -> str:
    """Prompt used by the diagnosis agent."""
    return (f"You are a biochar pyrolysis kiln process assistant. The data is SYNTHETIC (demo only).\n"
            f"Batch: {batch_id}\nAnomaly (from rule engine): {anomaly_json}\n"
            f"Sensor context from MCP tools (windows around the anomaly): {context_json}\n\n"
            "Explain the most probable cause in 2-4 sentences using ONLY the numbers given; do not invent values. "
            "Consider air leak (O2 up + temperature down), wet feedstock (moisture up + temperature down), "
            "sensor fault (flat-lined values). Reply as JSON: "
            '{"explanation": "...", "suggested_action": "...", "probable_cause": "air_leak|wet_feedstock|sensor_fault|other"}')

def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    ap.add_argument("--port", type=int, default=8765)
    a = ap.parse_args(argv)
    if a.transport == "streamable-http":
        mcp.settings.port = a.port  # binds 127.0.0.1 only
    mcp.run(transport=a.transport)

if __name__ == "__main__":
    main()
