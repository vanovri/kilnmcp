"""End-to-end CLI demo: simulate (or UART-replay) a SYNTHETIC batch with an injected fault,
then Monitor -> Diagnosis -> Reporting over MCP (stdio). Writes reports/.

  python -m kilnmcp.demo                 # real LLM via TokenMeter proxy
  python -m kilnmcp.demo --mock-llm      # no network
  python -m kilnmcp.demo --uart          # ingest via UART byte-stream replay
  python -m kilnmcp.demo --mock-llm --pdf  # also write reports/batch_<id>.pdf
  python -m kilnmcp.demo --profile lampung_coffee_corncob --mock-llm
"""
from __future__ import annotations
import argparse, asyncio, json, os, time
from pathlib import Path
from . import db, REPORT_BANNER, SYNTHETIC_BANNER
from .simulator import SimConfig, LAMPUNG_BATCH_ID, LAMPUNG_PROFILE_ID, lampung_config, ingest, parse_fault
from .llm import LLM, FakeLLM
from .agents import open_session, monitor_agent, diagnosis_agent, reporting_agent
from . import uart

async def run(args) -> dict:
    os.environ["KILNMCP_DB"] = str(Path(args.db or db.default_path()).resolve())
    profile = getattr(args, "profile", "default")
    if profile == LAMPUNG_PROFILE_ID:
        batch_id = args.batch if args.batch != "SYN-0001" else LAMPUNG_BATCH_ID
        seed = args.seed if args.seed != 42 else 2027
        cfg = lampung_config(batch_id=batch_id, seed=seed, faults=[parse_fault(f) for f in args.fault])
        args.batch = batch_id
    else:
        cfg = SimConfig(batch_id=args.batch, seed=args.seed, faults=[parse_fault(f) for f in args.fault])
    con = db.connect()
    t = {}; t0 = time.perf_counter()
    if args.uart:
        frames = str(Path(os.environ["KILNMCP_DB"]).parent / f"{args.batch}.frames")
        n = uart.write_frames(cfg, frames)
        ingest(con, cfg, source="uart")
        st = uart.replay(con, uart.file_chunks(frames, 64))
        print(f"[ingest] UART replay {frames}: {st}")
    else:
        n = ingest(con, cfg)
        print(f"[ingest] simulator: {n} readings")
    con.close()
    t["ingest_ms"] = (time.perf_counter() - t0) * 1000
    llm = FakeLLM() if args.mock_llm else LLM(model=args.model)
    print(f"[banner] {SYNTHETIC_BANNER} | LLM={llm.model} @ {llm.base_url}")
    async with open_session(args.http) as s:
        t1 = time.perf_counter(); ev = await monitor_agent(s, args.batch); t["monitor_ms"] = (time.perf_counter() - t1) * 1000
        for e in ev:
            print(f"[monitor] {e['rule']:<16} {e['sensor']:<13} peak={e['value']:<8} thr={e['threshold']} samples={e['samples']}")
        t1 = time.perf_counter(); dg = await diagnosis_agent(s, llm, args.batch, ev); t["diagnosis_ms"] = (time.perf_counter() - t1) * 1000
        for d in dg:
            print(f"[diagnosis] {d['anomaly']['rule']}: cause={d.get('probable_cause')} :: {str(d.get('explanation'))[:160]}")
        t1 = time.perf_counter(); path = await reporting_agent(s, llm, args.batch, args.out); t["reporting_ms"] = (time.perf_counter() - t1) * 1000
    print(f"[report] {path}  ({REPORT_BANNER})")
    pdf = None
    if getattr(args, "pdf", False):
        from .pdf import md_to_pdf
        pdf = md_to_pdf(path); print(f"[report] {pdf}")
    summary = {"synthetic": True, "certification_status": REPORT_BANNER, "batch_id": args.batch,
               "feedstock": cfg.feedstock, "anomaly_events": len(ev), "diagnosed": len(dg),
               "report": path, "report_pdf": pdf, "model": llm.model, "timings_ms": {k: round(v, 1) for k, v in t.items()},
               "llm_calls": llm.calls}
    Path(args.out, f"run_{args.batch}.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return summary

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--batch", default="SYN-0001"); ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--profile", choices=["default", LAMPUNG_PROFILE_ID], default="default",
                    help="Simulation profile (default corn_cob or lampung_coffee_corncob)")
    ap.add_argument("--fault", action="append", help="kind@start_min+duration_min, e.g. air_leak@60+6")
    ap.add_argument("--mock-llm", action="store_true"); ap.add_argument("--model", default=None)
    ap.add_argument("--uart", action="store_true", help="ingest via UART frame replay instead of direct sim")
    ap.add_argument("--http", default=None, help="Streamable HTTP MCP URL instead of stdio, e.g. http://127.0.0.1:8765/mcp")
    ap.add_argument("--pdf", action="store_true", help="also export the batch report as PDF")
    ap.add_argument("--db", default=None); ap.add_argument("--out", default="reports")
    a = ap.parse_args(argv)
    if a.fault is None:
        a.fault = [] if a.profile == LAMPUNG_PROFILE_ID else ["air_leak@60+6"]
    return asyncio.run(run(a))

if __name__ == "__main__":
    main()
