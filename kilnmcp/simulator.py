"""Deterministic (seeded) synthetic pyrolysis kiln simulator with injectable faults.

Output is SYNTHETIC. Values are illustrative shapes, not physics-calibrated.
"""
from __future__ import annotations
import json, math, random
from dataclasses import dataclass, field, asdict

T0 = 1798761600.0  # 2027-01-01T00:00:00Z fixed synthetic epoch (deterministic)

@dataclass
class Fault:
    kind: str            # air_leak | wet_feedstock | temp_sensor_stuck
    start_min: float
    duration_min: float
    magnitude: float = 1.0

@dataclass
class SimConfig:
    batch_id: str = "SYN-0001"
    seed: int = 42
    duration_min: int = 120
    step_s: int = 10
    input_mass_kg: float = 100.0
    yield_frac: float = 0.30
    feedstock: str = "corn_cob"
    base_moisture: float = 12.0
    faults: list[Fault] = field(default_factory=list)

def _active(f: Fault, m: float) -> float:
    """0..1 envelope of a fault at minute m (1-min soft ramps)."""
    if not (f.start_min <= m <= f.start_min + f.duration_min):
        return 0.0
    edge = min(m - f.start_min, f.start_min + f.duration_min - m)
    return min(1.0, edge / 1.0 + 0.2) * f.magnitude

def simulate(cfg: SimConfig):
    """Yield (ts, sensor, value) tuples, deterministic for a given cfg."""
    rng = random.Random(cfg.seed)
    steps = int(cfg.duration_min * 60 / cfg.step_s) + 1
    out_mass = cfg.input_mass_kg * cfg.yield_frac
    stuck_val = None
    for i in range(steps):
        m = i * cfg.step_s / 60.0
        ts = T0 + i * cfg.step_s
        # base profile: heat-up 20 min, steady, cool-down last 15 min
        if m < 20:
            temp = 25 + (600 - 25) * (m / 20)
        elif m > cfg.duration_min - 15:
            temp = 600 - (600 - 150) * ((m - (cfg.duration_min - 15)) / 15)
        else:
            temp = 600 + 15 * math.sin(m / 7)
        temp += rng.gauss(0, 4)
        o2 = 2.0 + rng.gauss(0, 0.25) + (6.0 if m < 5 else 0) * (1 - m / 5)
        moist = cfg.base_moisture * max(0.05, 1 - m / 60) + rng.gauss(0, 0.3)
        prog = min(1.0, max(0.0, (m - 10) / (cfg.duration_min - 30)))
        mass = cfg.input_mass_kg - (cfg.input_mass_kg - out_mass) * prog + rng.gauss(0, 0.2)
        for f in cfg.faults:
            a = _active(f, m)
            if not a:
                continue
            if f.kind == "air_leak":
                o2 += 7.0 * a
                temp -= 140 * a
            elif f.kind == "wet_feedstock":
                moist = max(moist, 28.0 * a)
                temp -= 90 * a
            elif f.kind == "temp_sensor_stuck":
                stuck_val = stuck_val if stuck_val is not None else round(temp, 1)
                temp = stuck_val
        yield ts, "temp_c", round(temp, 2)
        yield ts, "o2_pct", round(max(0.0, o2), 3)
        yield ts, "moisture_pct", round(max(0.0, moist), 2)
        yield ts, "mass_kg", round(mass, 2)

def ingest(con, cfg: SimConfig, source: str = "sim") -> int:
    rows = list(simulate(cfg))
    con.execute("DELETE FROM readings WHERE batch_id=?", (cfg.batch_id,))
    for t in ("anomalies", "events", "reports"):
        con.execute(f"DELETE FROM {t} WHERE batch_id=?", (cfg.batch_id,))
    con.execute("INSERT OR REPLACE INTO batches VALUES(?,?,?,?,?,?,?,?,1)", (
        cfg.batch_id, rows[0][0], rows[-1][0], cfg.feedstock, cfg.input_mass_kg,
        [r for r in rows if r[1] == "mass_kg"][-1][2], cfg.seed,
        json.dumps([asdict(f) for f in cfg.faults])))
    if source == "sim":
        con.executemany("INSERT INTO readings(batch_id,ts,sensor,value,source) VALUES(?,?,?,?,?)",
                        [(cfg.batch_id, ts, s, v, source) for ts, s, v in rows])
    con.commit()
    return len(rows)

def parse_fault(spec: str) -> Fault:
    """'air_leak@60+8' or 'air_leak@60+8x1.0'"""
    kind, rest = spec.split("@")
    start, rest = rest.split("+")
    dur, _, mag = rest.partition("x")
    return Fault(kind, float(start), float(dur), float(mag or 1.0))
