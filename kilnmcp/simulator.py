"""Deterministic (seeded) synthetic pyrolysis kiln simulator with injectable faults.

Output is SYNTHETIC. Values are illustrative shapes, not physics-calibrated.
"""
from __future__ import annotations
import json, math, random
from dataclasses import dataclass, field, asdict
from . import CERTIFICATION_STATUS, SYNTHETIC_BANNER

T0 = 1798761600.0  # 2027-01-01T00:00:00Z fixed synthetic epoch (deterministic)

LAMPUNG_PROFILE_ID = "lampung_coffee_corncob"
LAMPUNG_BATCH_ID = "BATCH-LPG-2027-001"
LAMPUNG_TARGET_TEMP_RANGE_C = (450.0, 650.0)
LAMPUNG_FEEDSTOCK_BLEND = {"coffee_shell_pct": 55.0, "corn_cob_pct": 45.0}

LAMPUNG_PARAMS = {
    "synthetic": True,
    "certification_status": CERTIFICATION_STATUS,
    "banner": SYNTHETIC_BANNER,
    "profile_id": LAMPUNG_PROFILE_ID,
    "default_batch_id": LAMPUNG_BATCH_ID,
    "organization": "PT ENVIID Karbon Solusi",
    "region": "Lampung, Indonesia (Ultisol upland plots)",
    "feedstock": LAMPUNG_PROFILE_ID,
    "feedstock_blend": LAMPUNG_FEEDSTOCK_BLEND,
    "target_temp_zone_c": [450.0, 650.0],
    "nominal_temp_c": 560.0,
    "input_mass_kg": 800.0,
    "dry_yield_frac": 0.25,
    "c_org_frac": 0.70,
    "h_c_org_molar_nominal": 0.42,
    "h_c_org_molar_max": 0.70,
    "co2_to_c_molar_ratio": 44.0 / 12.0,
    "permanence_factor": 0.80,
    "safety_factor": 0.90,
    "ultisol_rate_t_per_ha": 2.0,
    "ultisol_rate_kg_per_ha": 2000.0,
}

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
    target_temp_c: float = 600.0

    def __post_init__(self):
        if self.feedstock == LAMPUNG_PROFILE_ID:
            if self.yield_frac == 0.30:
                self.yield_frac = 0.25
            if self.target_temp_c == 600.0:
                self.target_temp_c = 560.0

LAMPUNG_FAULT_PRESETS: dict[str, dict] = {
    "nominal": {
        "preset_id": "nominal",
        "label": "Nominal Lampung Coffee+Corn-Cob Batch (BATCH-LPG-2027-001)",
        "batch_id": LAMPUNG_BATCH_ID,
        "faults": [],
        "h_c_org_molar": 0.42,
    },
    "wet_feedstock": {
        "preset_id": "wet_feedstock",
        "label": "Wet Coffee-Husk Fault (wet_feedstock > 20% MC)",
        "batch_id": "BATCH-LPG-2027-WET",
        "faults": [Fault("wet_feedstock", 50.0, 10.0, 1.0)],
        "h_c_org_molar": 0.66,
    },
    "air_leak": {
        "preset_id": "air_leak",
        "label": "Kiln Air-Leak Fault (air_leak O2 spike)",
        "batch_id": "BATCH-LPG-2027-AIR",
        "faults": [Fault("air_leak", 60.0, 8.0, 1.0)],
        "h_c_org_molar": 0.64,
    },
    "temp_sensor_stuck": {
        "preset_id": "temp_sensor_stuck",
        "label": "Thermocouple Stuck Fault (temp_sensor_stuck)",
        "batch_id": "BATCH-LPG-2027-STK",
        "faults": [Fault("temp_sensor_stuck", 45.0, 20.0, 1.0)],
        "h_c_org_molar": 0.45,
    },
}

def lampung_config(
    batch_id: str = LAMPUNG_BATCH_ID,
    seed: int = 2027,
    input_mass_kg: float = 800.0,
    faults: list[Fault] | None = None,
    preset: str | None = None,
    duration_min: int = 120,
    step_s: int = 10,
) -> SimConfig:
    """Create a deterministic SimConfig for PT ENVIID Karbon Solusi's Lampung pyrolysis profile."""
    if preset:
        if preset not in LAMPUNG_FAULT_PRESETS:
            raise ValueError(f"unknown Lampung preset {preset!r}; expected one of {tuple(LAMPUNG_FAULT_PRESETS)}")
        p = LAMPUNG_FAULT_PRESETS[preset]
        if batch_id == LAMPUNG_BATCH_ID:
            batch_id = p["batch_id"]
        if faults is None:
            faults = [Fault(f.kind, f.start_min, f.duration_min, f.magnitude) for f in p["faults"]]
    return SimConfig(
        batch_id=batch_id,
        seed=seed,
        duration_min=duration_min,
        step_s=step_s,
        input_mass_kg=input_mass_kg,
        yield_frac=0.25,
        feedstock=LAMPUNG_PROFILE_ID,
        base_moisture=12.5,
        faults=list(faults or []),
        target_temp_c=560.0,
    )

def compute_lampung_carbon(
    dry_biochar_kg: float,
    c_org_frac: float = 0.70,
    h_c_org_molar: float = 0.42,
    permanence_factor: float = 0.80,
    safety_factor: float = 0.90,
) -> dict:
    """Stoichiometric 44/12 * 0.80 * 0.90 net CO2e calculation for Lampung biochar."""
    stored_c_org_kg = round(dry_biochar_kg * c_org_frac, 4)
    co2_c_ratio = 44.0 / 12.0
    gross_co2e_kg = round(stored_c_org_kg * co2_c_ratio, 4)
    perm_co2e_kg = round(stored_c_org_kg * co2_c_ratio * permanence_factor, 4)
    net_co2e_kg = round(stored_c_org_kg * co2_c_ratio * permanence_factor * safety_factor, 4)
    return {
        "synthetic": True,
        "certification_status": CERTIFICATION_STATUS,
        "banner": SYNTHETIC_BANNER,
        "dry_biochar_kg": round(dry_biochar_kg, 2),
        "c_org_frac": c_org_frac,
        "stored_c_org_kg": stored_c_org_kg,
        "h_c_org_molar": round(h_c_org_molar, 3),
        "h_c_org_threshold_max": 0.70,
        "h_c_org_compliant": bool(h_c_org_molar < 0.70),
        "co2_to_c_molar_ratio": round(co2_c_ratio, 6),
        "permanence_factor": permanence_factor,
        "safety_factor": safety_factor,
        "gross_co2e_kg": gross_co2e_kg,
        "permanence_adjusted_co2e_kg": perm_co2e_kg,
        "net_co2e_kg": net_co2e_kg,
        "net_co2e_tonnes": round(net_co2e_kg / 1000.0, 6),
        "formula": "net_co2e_kg = dry_biochar_kg * 0.70 * (44/12) * 0.80 * 0.90",
    }

def reconcile_lampung_bags(
    batch_id: str,
    output_mass_kg: float,
    input_mass_kg: float = 800.0,
    bag_mode: str = "mixed",
    lab_sample_kg: float = 1.0,
    c_org_frac: float = 0.70,
) -> dict:
    """QR bag-level mass reconciliation (25 kg / 50 kg bags) for 2 t/ha Ultisol soil plots."""
    if bag_mode not in ("mixed", "50kg", "25kg"):
        raise ValueError(f"unknown bag_mode {bag_mode!r}; expected 'mixed', '50kg', or '25kg'")
    output_mass_kg = round(max(0.0, float(output_mass_kg)), 2)
    lab_sample_kg = round(min(lab_sample_kg, output_mass_kg * 0.05), 2)
    handling_loss_kg = round(min(output_mass_kg * 0.004, max(0.0, output_mass_kg - lab_sample_kg)), 2)
    baggable_kg = round(max(0.0, output_mass_kg - lab_sample_kg - handling_loss_kg), 2)

    specs: list[tuple[int, float]] = []
    rem = baggable_kg
    if bag_mode == "50kg":
        while rem > 0.001:
            take = round(min(50.0, rem), 2)
            specs.append((50, take))
            rem = round(rem - take, 2)
    elif bag_mode == "25kg":
        while rem > 0.001:
            take = round(min(25.0, rem), 2)
            specs.append((25, take))
            rem = round(rem - take, 2)
    else:
        # Mixed mode: pack ~75% into 50 kg bags, remainder into 25 kg bags
        target_50 = round(baggable_kg * 0.75, 2)
        while rem > 0.001 and (baggable_kg - rem) + 49.0 <= target_50 + 5.0 and rem >= 45.0:
            take = round(min(50.0, rem), 2)
            specs.append((50, take))
            rem = round(rem - take, 2)
        while rem > 0.001:
            take = round(min(25.0, rem), 2)
            specs.append((25, take))
            rem = round(rem - take, 2)

    bags = []
    co2_mult = c_org_frac * (44.0 / 12.0) * 0.80 * 0.90
    applied_cutoff = max(1, int(math.ceil(len(specs) * 0.6)))
    for idx, (bag_class, net_kg) in enumerate(specs, 1):
        tare_kg = 0.45 if bag_class == 50 else 0.28
        gross_kg = round(net_kg + tare_kg, 2)
        plot_num = (idx - 1) // 2 + 1
        plot_sub = chr(65 + ((idx - 1) % 2))
        plot_id = f"LMP-ULT-{plot_num:02d}{plot_sub}"
        area_ha = round(net_kg / 2000.0, 5)
        area_m2 = round(area_ha * 10000.0, 1)
        status = "APPLIED_ULTISOL" if idx <= applied_cutoff else "IN_INVENTORY_TAGGED"
        bags.append({
            "bag_index": idx,
            "qr_code": f"QR-{batch_id}-B{idx:02d}",
            "bag_class_kg": bag_class,
            "net_mass_kg": net_kg,
            "tare_mass_kg": tare_kg,
            "gross_mass_kg": gross_kg,
            "c_org_kg": round(net_kg * c_org_frac, 3),
            "net_co2e_kg": round(net_kg * co2_mult, 3),
            "ultisol_plot_id": plot_id,
            "soil_order": "Ultisol (Lampung acid upland)",
            "application_rate_t_per_ha": 2.0,
            "plot_coverage_ha": area_ha,
            "plot_coverage_m2": area_m2,
            "dispatch_status": status,
        })

    total_bag_net_kg = round(sum(b["net_mass_kg"] for b in bags), 2)
    total_bag_gross_kg = round(sum(b["gross_mass_kg"] for b in bags), 2)
    accounted_mass_kg = round(total_bag_net_kg + lab_sample_kg + handling_loss_kg, 2)
    discrepancy_kg = round(output_mass_kg - accounted_mass_kg, 4)
    total_area_ha = round(total_bag_net_kg / 2000.0, 4)
    applied_net_kg = round(sum(b["net_mass_kg"] for b in bags if b["dispatch_status"] == "APPLIED_ULTISOL"), 2)
    inventory_net_kg = round(sum(b["net_mass_kg"] for b in bags if b["dispatch_status"] != "APPLIED_ULTISOL"), 2)

    return {
        "synthetic": True,
        "certification_status": CERTIFICATION_STATUS,
        "banner": SYNTHETIC_BANNER,
        "batch_id": batch_id,
        "bag_mode": bag_mode,
        "input_mass_kg": round(input_mass_kg, 2),
        "kiln_output_mass_kg": output_mass_kg,
        "actual_yield_frac": round(output_mass_kg / input_mass_kg, 4) if input_mass_kg else 0.0,
        "actual_yield_pct": round((output_mass_kg / input_mass_kg) * 100.0, 2) if input_mass_kg else 0.0,
        "target_yield_pct": 25.0,
        "lab_sample_id": f"LAB-{batch_id}-S01",
        "lab_sample_kg": lab_sample_kg,
        "handling_loss_kg": handling_loss_kg,
        "total_bag_net_kg": total_bag_net_kg,
        "total_bag_gross_kg": total_bag_gross_kg,
        "applied_ultisol_kg": applied_net_kg,
        "inventory_tagged_kg": inventory_net_kg,
        "accounted_mass_kg": accounted_mass_kg,
        "mass_discrepancy_kg": discrepancy_kg,
        "reconciled": abs(discrepancy_kg) <= 0.05,
        "ultisol_rate_t_per_ha": 2.0,
        "total_ultisol_area_ha": total_area_ha,
        "total_ultisol_area_m2": round(total_area_ha * 10000.0, 1),
        "applied_ultisol_area_ha": round(applied_net_kg / 2000.0, 4),
        "bag_count": len(bags),
        "bags_50kg_count": sum(1 for b in bags if b["bag_class_kg"] == 50),
        "bags_25kg_count": sum(1 for b in bags if b["bag_class_kg"] == 25),
        "bags": bags,
    }

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
        t_target = int(cfg.target_temp_c) if cfg.target_temp_c == int(cfg.target_temp_c) else cfg.target_temp_c
        if m < 20:
            temp = 25 + (t_target - 25) * (m / 20)
        elif m > cfg.duration_min - 15:
            temp = t_target - (t_target - 150) * ((m - (cfg.duration_min - 15)) / 15)
        else:
            temp = t_target + 15 * math.sin(m / 7)
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
