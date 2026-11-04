import asyncio
import json
from pathlib import Path
from kilnmcp import CERTIFICATION_STATUS, db, demo
from kilnmcp.agents import call, open_session
from kilnmcp.simulator import (
    LAMPUNG_BATCH_ID,
    LAMPUNG_FAULT_PRESETS,
    LAMPUNG_PARAMS,
    LAMPUNG_PROFILE_ID,
    SimConfig,
    compute_lampung_carbon,
    ingest,
    lampung_config,
    reconcile_lampung_bags,
    simulate,
)
from kilnmcp.workbench import (
    build_all_scenarios,
    evaluate_lampung_batch,
    render_workbench_html,
    write_workbench,
)

ROOT = Path(__file__).resolve().parent.parent
ENVIID_VERIFICATION_HTML = Path(r"C:\Users\ardhy\enviid-redesign\verification\kilnmcp-workbench.html")


def test_lampung_profile_deterministic_and_target_zone():
    cfg1 = lampung_config()
    cfg2 = lampung_config()
    assert cfg1.batch_id == LAMPUNG_BATCH_ID == "BATCH-LPG-2027-001"
    assert cfg1.feedstock == LAMPUNG_PROFILE_ID == "lampung_coffee_corncob"
    assert cfg1.yield_frac == 0.25
    assert cfg1.target_temp_c == 560.0

    rows1 = list(simulate(cfg1))
    rows2 = list(simulate(cfg2))
    assert rows1 == rows2

    bundle = evaluate_lampung_batch("nominal")
    assert bundle["synthetic"] is True
    assert bundle["certification_status"] == "dMRV-style DRAFT - NOT CERTIFIED"
    assert bundle["anomalies"] == []
    assert bundle["quality_gate"] == "PASS_DRAFT_CRITERIA"
    sm = bundle["steady_metrics"]
    assert 450.0 <= sm["temp_min_c"] <= sm["temp_mean_c"] <= sm["temp_max_c"] <= 650.0
    assert sm["in_target_zone_pct"] == 100.0


def test_lampung_stoichiometric_carbon_accounting():
    carb = compute_lampung_carbon(200.0)
    assert carb["synthetic"] is True
    assert carb["certification_status"] == CERTIFICATION_STATUS
    assert carb["c_org_frac"] == 0.70
    assert carb["stored_c_org_kg"] == 140.0
    assert carb["h_c_org_molar"] == 0.42
    assert carb["h_c_org_molar"] < 0.70
    assert carb["h_c_org_compliant"] is True
    # Exact stoichiometry: 140 * (44/12) * 0.80 * 0.90 = 369.6 kg CO2e
    expected_net = round(140.0 * (44.0 / 12.0) * 0.80 * 0.90, 4)
    assert carb["net_co2e_kg"] == expected_net == 369.6
    assert carb["net_co2e_tonnes"] == 0.3696


def test_qr_bag_mass_reconciliation_modes():
    for mode in ("mixed", "50kg", "25kg"):
        rec = reconcile_lampung_bags(LAMPUNG_BATCH_ID, output_mass_kg=200.02, input_mass_kg=800.0, bag_mode=mode)
        assert rec["synthetic"] is True
        assert rec["certification_status"] == "dMRV-style DRAFT - NOT CERTIFIED"
        assert rec["reconciled"] is True
        assert abs(rec["mass_discrepancy_kg"]) <= 0.05
        assert round(rec["total_bag_net_kg"] + rec["lab_sample_kg"] + rec["handling_loss_kg"], 2) == 200.02
        assert rec["ultisol_rate_t_per_ha"] == 2.0
        assert rec["total_ultisol_area_ha"] == round(rec["total_bag_net_kg"] / 2000.0, 4)
        assert len(rec["bags"]) >= 4
        for b in rec["bags"]:
            assert b["qr_code"].startswith(f"QR-{LAMPUNG_BATCH_ID}-B")
            assert b["bag_class_kg"] in (25, 50)
            assert b["ultisol_plot_id"].startswith("LMP-ULT-")
            assert b["application_rate_t_per_ha"] == 2.0

    mixed = reconcile_lampung_bags(LAMPUNG_BATCH_ID, output_mass_kg=200.0, bag_mode="mixed")
    assert mixed["bags_50kg_count"] >= 1 and mixed["bags_25kg_count"] >= 1


def test_lampung_fault_modes_detected():
    scenarios = build_all_scenarios()
    assert set(scenarios.keys()) == {"nominal", "wet_feedstock", "air_leak", "temp_sensor_stuck"}

    # 1. Nominal clean batch
    assert scenarios["nominal"]["anomalies"] == []

    # 2. Wet coffee-husk fault (>20% MC)
    wet_rules = {a["rule"] for a in scenarios["wet_feedstock"]["anomalies"]}
    assert "R-MOIST-HIGH" in wet_rules
    assert "R-TEMP-LOW" in wet_rules
    assert any(a["diagnosis"]["probable_cause"] == "wet_feedstock" for a in scenarios["wet_feedstock"]["anomalies"])

    # 3. Kiln air-leak fault (O2 spike > 5%)
    air_rules = {a["rule"] for a in scenarios["air_leak"]["anomalies"]}
    assert {"R-O2-HIGH", "R-TEMP-LOW"} <= air_rules
    assert any(a["diagnosis"]["probable_cause"] == "air_leak" for a in scenarios["air_leak"]["anomalies"])

    # 4. Thermocouple stuck fault (flatline)
    stuck_rules = {a["rule"] for a in scenarios["temp_sensor_stuck"]["anomalies"]}
    assert "R-EWMA-STUCK-temp_c" in stuck_rules
    assert any(a["diagnosis"]["probable_cause"] == "sensor_fault" for a in scenarios["temp_sensor_stuck"]["anomalies"])


def test_mcp_lampung_tools_and_demo_epistemic_honesty(dbpath, tmp_path):
    cfg = lampung_config()
    ingest(db.connect(dbpath), cfg)

    async def verify_mcp():
        async with open_session() as s:
            b = await call(s, "get_batch", batch_id=LAMPUNG_BATCH_ID)
            assert b["synthetic"] is True
            assert b["certification_status"] == "dMRV-style DRAFT - NOT CERTIFIED"
            assert b["feedstock"] == LAMPUNG_PROFILE_ID
            assert "lampung_dmrv" in b
            assert b["lampung_dmrv"]["carbon_accounting"]["c_org_frac"] == 0.70

            dmrv = await call(s, "get_lampung_dmrv", batch_id=LAMPUNG_BATCH_ID, bag_mode="mixed")
            assert dmrv["synthetic"] is True
            assert dmrv["certification_status"] == "dMRV-style DRAFT - NOT CERTIFIED"
            assert dmrv["bag_reconciliation"]["reconciled"] is True

            res = await s.read_resource("kiln://profiles/lampung_coffee_corncob")
            prof = json.loads(res.contents[0].text)
            assert prof["synthetic"] is True
            assert prof["certification_status"] == "dMRV-style DRAFT - NOT CERTIFIED"
            assert prof["target_temp_zone_c"] == [450.0, 650.0]

    asyncio.run(verify_mcp())

    out_dir = tmp_path / "reports"
    summary = demo.main([
        "--profile", LAMPUNG_PROFILE_ID,
        "--fault", "wet_feedstock@50+10",
        "--mock-llm",
        "--out", str(out_dir),
        "--db", dbpath,
    ])
    assert summary["synthetic"] is True
    assert summary["certification_status"] == "dMRV-style DRAFT - NOT CERTIFIED"
    assert summary["batch_id"] == LAMPUNG_BATCH_ID
    md_text = Path(summary["report"]).read_text(encoding="utf-8")
    assert "Lampung Pyrolysis Carbon Accounting & QR Bag Reconciliation" in md_text
    assert "dMRV-style DRAFT - NOT CERTIFIED" in md_text


def test_workbench_html_generation_and_mirror(tmp_path):
    web_out = ROOT / "web" / "index.html"
    mirrors = [tmp_path / "kilnmcp-workbench.html"]
    if ENVIID_VERIFICATION_HTML.parent.exists():
        mirrors.append(ENVIID_VERIFICATION_HTML)

    written = write_workbench(web_out, mirrors)
    assert Path(written[0]).exists()
    html = web_out.read_text(encoding="utf-8")

    # Verify required UI sections, scenarios, dual canvases, UART inspector, QR bag table, and epistemic honesty
    for required_token in (
        "PT ENVIID Karbon Solusi",
        "BATCH-LPG-2027-001",
        "wet_feedstock",
        "air_leak",
        "temp_sensor_stuck",
        "dMRV-style DRAFT - NOT CERTIFIED",
        '"synthetic":true',
        "canvas-temp",
        "canvas-moist-o2",
        "$KILN,",
        "LMP-ULT-01A",
        "btn-export-json",
        "btn-export-md",
        "@container (width < 600px)",
    ):
        assert required_token in html, f"missing {required_token!r} in workbench HTML"

    if ENVIID_VERIFICATION_HTML.parent.exists():
        assert ENVIID_VERIFICATION_HTML.exists()
        assert ENVIID_VERIFICATION_HTML.read_text(encoding="utf-8") == html
