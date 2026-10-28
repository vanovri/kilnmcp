import asyncio, json, os, socket, subprocess, sys, time
from pathlib import Path
import pytest
from kilnmcp import demo, db
from kilnmcp.agents import open_session, call
from kilnmcp.simulator import SimConfig, ingest

ROOT = Path(__file__).resolve().parent.parent

def test_stdio_tools_resources_prompt(dbpath):
    ingest(db.connect(), SimConfig(batch_id="T1"))
    async def go():
        async with open_session() as s:
            tools = {t.name for t in (await s.list_tools()).tools}
            assert {"get_latest", "get_window", "get_batch", "list_anomalies", "log_event"} <= tools
            r = await call(s, "get_latest", sensor="temp_c", batch_id="T1")
            assert r["synthetic"] is True and r["value"] is not None
            w = await call(s, "get_window", sensor="o2_pct", minutes=10, batch_id="T1")
            assert w["stats"]["n"] == 60
            res = await s.read_resource("kiln://batches/T1")
            assert json.loads(res.contents[0].text)["synthetic"] is True
            assert "rules" in (await s.read_resource("kiln://thresholds")).contents[0].text
            assert "readings" in (await s.read_resource("kiln://schema")).contents[0].text
            p = await s.get_prompt("diagnose_anomaly", {"batch_id": "T1", "anomaly_json": "{}", "context_json": "{}"})
            assert "SYNTHETIC" in p.messages[0].content.text
            bad = await s.call_tool("get_latest", {"sensor": "nope"})
            assert bad.isError
    asyncio.run(go())

def test_demo_mock_end_to_end(dbpath, tmp_path):
    out = tmp_path / "reports"
    s = demo.main(["--mock-llm", "--out", str(out), "--db", dbpath])
    assert s["anomaly_events"] >= 2 and s["diagnosed"] == 1
    md = Path(s["report"]).read_text(encoding="utf-8")
    assert "dMRV-style DRAFT - NOT CERTIFIED" in md and "SYNTHETIC" in md and "R-O2-HIGH" in md
    con = db.connect(dbpath)
    assert con.execute("SELECT status FROM reports").fetchone()[0] == "DRAFT_NOT_CERTIFIED"
    assert con.execute("SELECT COUNT(*) FROM diagnoses").fetchone()[0] == s["anomaly_events"]

def test_demo_uart_mode(dbpath, tmp_path):
    s = demo.main(["--mock-llm", "--uart", "--batch", "U2", "--out", str(tmp_path), "--db", dbpath])
    assert s["anomaly_events"] >= 2
    assert "uart" in Path(s["report"]).read_text(encoding="utf-8")

def _free_port():
    with socket.socket() as so:
        so.bind(("127.0.0.1", 0)); return so.getsockname()[1]

def test_streamable_http(dbpath):
    ingest(db.connect(), SimConfig(batch_id="H1"))
    port = _free_port()
    p = subprocess.Popen([sys.executable, "-m", "kilnmcp.server", "--transport", "streamable-http", "--port", str(port)],
                         cwd=ROOT, env=dict(os.environ))
    try:
        for _ in range(100):
            try:
                socket.create_connection(("127.0.0.1", port), 0.2).close(); break
            except OSError:
                time.sleep(0.1)
        async def go():
            async with open_session(f"http://127.0.0.1:{port}/mcp") as s:
                b = await call(s, "get_batch", batch_id="H1")
                assert b["synthetic"] is True and b["sensor_summary"]["temp_c"]["n"] == 721
        asyncio.run(go())
    finally:
        p.terminate(); p.wait(10)
