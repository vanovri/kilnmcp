import yaml
from pathlib import Path
from kilnmcp import db, uart
from kilnmcp.simulator import SimConfig, simulate, ingest, parse_fault
from kilnmcp.agents import detect

CFG = yaml.safe_load(Path(__file__).resolve().parent.parent.joinpath("config/thresholds.yaml").read_text())

def _readings(cfg):
    r = {}
    for ts, s, v in simulate(cfg):
        r.setdefault(s, []).append([ts, v])
    return r

def _detect(cfg):
    rs = _readings(cfg); ts = [t for t, _ in rs["temp_c"]]
    return detect(rs, CFG, ts[0], ts[-1])

def test_deterministic():
    a = list(simulate(SimConfig(seed=1))); b = list(simulate(SimConfig(seed=1)))
    assert a == b and a != list(simulate(SimConfig(seed=2)))

def test_no_false_positives_clean_batches():
    for seed in range(10):
        assert _detect(SimConfig(seed=seed)) == [], seed

def test_air_leak_detected():
    ev = _detect(SimConfig(faults=[parse_fault("air_leak@60+6")]))
    rules = {e["rule"] for e in ev}
    assert {"R-O2-HIGH", "R-TEMP-LOW"} <= rules
    o2 = next(e for e in ev if e["rule"] == "R-O2-HIGH")
    assert 60 * 60 <= o2["ts"] - 1798761600.0 <= 62 * 60

def test_wet_feedstock_detected():
    assert "R-MOIST-HIGH" in {e["rule"] for e in _detect(SimConfig(faults=[parse_fault("wet_feedstock@50+8")]))}

def test_stuck_sensor_flagged_by_ewma_or_not_crash():
    _detect(SimConfig(faults=[parse_fault("temp_sensor_stuck@40+20")]))

def test_uart_roundtrip_with_garbage_and_fragmentation(tmp_path, dbpath):
    cfg = SimConfig(batch_id="U1", duration_min=5)
    f = tmp_path / "x.frames"; n = uart.write_frames(cfg, str(f))
    data = b"\x00\xffnoise\r\n" + f.read_bytes() + b"$KILN,U1,1,temp_c,5*00\r\n"
    chunks = [data[i:i + 7] for i in range(0, len(data), 7)]
    con = db.connect(); ingest(con, cfg, source="uart")
    st = uart.replay(con, chunks)
    assert st == {"ok": n, "bad": 2}
    got = con.execute("SELECT ts,sensor,value FROM readings WHERE batch_id='U1' ORDER BY id").fetchall()
    assert [tuple(r) for r in got] == list(simulate(cfg))
    assert {r[0] for r in con.execute("SELECT source FROM readings")} == {"uart"}

def test_batch_marked_synthetic(dbpath):
    con = db.connect(); ingest(con, SimConfig())
    assert con.execute("SELECT synthetic FROM batches").fetchone()[0] == 1
