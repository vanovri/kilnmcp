"""Plain-Python agents talking to the KilnMCP server through an MCP ClientSession."""
from __future__ import annotations
import json, os, sys, datetime as dt
from contextlib import asynccontextmanager
from pathlib import Path
import yaml
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from . import REPORT_BANNER, SYNTHETIC_BANNER
from .llm import parse_json

@asynccontextmanager
async def open_session(http_url: str | None = None):
    """stdio (spawns `python -m kilnmcp.server`) or Streamable HTTP if http_url given."""
    if http_url:
        try:
            from mcp.client.streamable_http import streamable_http_client as _c
        except ImportError:
            from mcp.client.streamable_http import streamablehttp_client as _c
        async with _c(http_url) as (r, w, _):
            async with ClientSession(r, w) as s:
                await s.initialize(); yield s
    else:
        params = StdioServerParameters(command=sys.executable, args=["-m", "kilnmcp.server"],
                                       env=dict(os.environ), cwd=str(Path(__file__).resolve().parent.parent))
        async with stdio_client(params) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize(); yield s

async def call(s: ClientSession, tool: str, **args) -> dict:
    res = await s.call_tool(tool, args)
    if res.isError:
        raise RuntimeError(f"tool {tool} failed: {res.content}")
    if res.structuredContent is not None:
        sc = res.structuredContent
        return sc.get("result", sc) if set(sc) == {"result"} else sc
    return json.loads(res.content[0].text)

def iso(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

# ---------------- Monitor (no LLM) ----------------
OPS = {"<": lambda v, t: v < t, ">": lambda v, t: v > t}

def detect(readings: dict[str, list], cfg: dict, start_ts: float, end_ts: float, step_s: float = 10) -> list[dict]:
    """Rules + EWMA on steady-phase samples; contiguous hits grouped into one event."""
    lo = start_ts + cfg.get("warmup_minutes", 0) * 60
    hi = end_ts - cfg.get("cooldown_minutes", 0) * 60
    hits: list[tuple] = []  # (rule, sensor, ts, value, threshold, severity, worse_is_higher)
    for rule, r in cfg["rules"].items():
        for ts, v in readings.get(r["sensor"], []):
            if lo <= ts <= hi and OPS[r["op"]](v, r["value"]):
                hits.append((rule, r["sensor"], ts, v, r["value"], r["severity"], r["op"] == ">"))
    e = cfg.get("ewma") or {}
    for sensor in e.get("sensors", []):
        mean = var = None; n = 0
        for ts, v in readings.get(sensor, []):
            if mean is None:
                mean, var = v, 0.0
            sd = var ** 0.5
            if lo <= ts <= hi and n >= e["min_samples"] and sd > 0 and abs(v - mean) > e["k_sigma"] * sd:
                hits.append((f"R-EWMA-{sensor}", sensor, ts, v, round(e["k_sigma"] * sd, 3), "low", v > mean))
            else:  # only learn from normal points so a long fault does not become 'normal'
                d = v - mean; mean += e["alpha"] * d; var = (1 - e["alpha"]) * (var + e["alpha"] * d * d)
            n += 1
    events = []
    for key in sorted({(h[0], h[1]) for h in hits}):
        hs = sorted([h for h in hits if (h[0], h[1]) == key], key=lambda h: h[2])
        cur = None
        for h in hs:
            if cur and h[2] - cur["end_ts"] <= 3 * step_s:
                cur["end_ts"] = h[2]; cur["samples"] += 1
                if (h[3] > cur["value"]) == h[6]: cur["value"] = h[3]
            else:
                cur = {"rule": h[0], "sensor": h[1], "ts": h[2], "end_ts": h[2], "value": h[3],
                       "threshold": h[4], "severity": h[5], "samples": 1}
                events.append(cur)
    min_run = e.get("min_run", 1)
    events = [x for x in events if not x["rule"].startswith("R-EWMA") or x["samples"] >= min_run]
    return sorted(events, key=lambda x: x["ts"])

async def monitor_agent(s: ClientSession, batch_id: str, thresholds_yaml: str | None = None) -> list[dict]:
    if thresholds_yaml is None:
        r = await s.read_resource("kiln://thresholds"); thresholds_yaml = r.contents[0].text
    cfg = yaml.safe_load(thresholds_yaml)
    b = await call(s, "get_batch", batch_id=batch_id)
    minutes = b["duration_min"] + 1
    readings = {}
    for sensor in ("temp_c", "o2_pct", "moisture_pct"):
        w = await call(s, "get_window", sensor=sensor, minutes=minutes, batch_id=batch_id)
        readings[sensor] = w["readings"]
    events = detect(readings, cfg, b["start_ts"], b["end_ts"])
    for ev in events:
        ev["anomaly_id"] = (await call(s, "record_anomaly", batch_id=batch_id, **ev))["anomaly_id"]
    await call(s, "log_event", batch_id=batch_id, kind="monitor", note=f"{len(events)} anomaly events")
    return events

# ---------------- Diagnosis (LLM) ----------------
def incidents(events: list[dict], gap_s: float = 300) -> list[list[dict]]:
    """Group co-occurring anomaly events (overlapping or within gap_s) into incidents."""
    out: list[list[dict]] = []
    for e in sorted(events, key=lambda e: e["ts"]):
        if out and e["ts"] - max(x["end_ts"] for x in out[-1]) <= gap_s:
            out[-1].append(e)
        else:
            out.append([e])
    return out

async def diagnosis_agent(s: ClientSession, llm, batch_id: str, events: list[dict], max_incidents: int = 3) -> list[dict]:
    """One LLM call per incident; the diagnosis is attached to every anomaly in the incident."""
    out = []
    for inc in incidents(events)[:max_incidents]:
        ev = sorted(inc, key=lambda e: (e["severity"] != "high", e["ts"]))[0]
        t_end = max(e["end_ts"] for e in inc)
        ctx = {}
        for sensor in ("temp_c", "o2_pct", "moisture_pct"):
            w = await call(s, "get_window", sensor=sensor, minutes=10, batch_id=batch_id, end_ts=t_end + 120)
            ctx[f"{sensor}_window_10min"] = w["stats"]
            w = await call(s, "get_window", sensor=sensor, minutes=10, batch_id=batch_id, end_ts=min(e["ts"] for e in inc) - 60)
            ctx[f"{sensor}_baseline_before"] = w["stats"]
        anomaly = {k: ev[k] for k in ("rule", "sensor", "value", "threshold", "severity", "samples")}
        anomaly["start"], anomaly["end"] = iso(min(e["ts"] for e in inc)), iso(t_end)
        anomaly["co_occurring_rules"] = sorted({e["rule"] for e in inc})
        p = await s.get_prompt("diagnose_anomaly", {"batch_id": batch_id, "anomaly_json": json.dumps(anomaly),
                                                    "context_json": json.dumps(ctx)})
        msgs = [{"role": m.role, "content": m.content.text} for m in p.messages]
        d = parse_json(llm.chat(msgs, agent="diagnosis"))
        for e in inc:
            await call(s, "save_diagnosis", anomaly_id=e["anomaly_id"], model=llm.model,
                       explanation=str(d.get("explanation", "")), suggested_action=str(d.get("suggested_action", "")))
        out.append({"anomaly": anomaly, **d})
    return out

# ---------------- Reporting (LLM narrative, numbers from SQL) ----------------
async def reporting_agent(s: ClientSession, llm, batch_id: str, out_dir: str = "reports") -> str:
    b = await call(s, "get_batch", batch_id=batch_id)
    an = (await call(s, "list_anomalies", batch_id=batch_id))["anomalies"]
    facts = {"batch_id": batch_id, "feedstock": b["feedstock"], "duration_min": b["duration_min"],
             "input_mass_kg": b["input_mass_kg"], "output_mass_kg": b["output_mass_kg"],
             "anomalies": [{"rule": a["rule"], "start": iso(a["ts"]), "samples": a["samples"],
                            "diagnosis": (a["diagnoses"][0]["explanation"] if a["diagnoses"] else None)} for a in an]}
    narrative = llm.chat([
        {"role": "system", "content": "You write short batch-log narratives for a SYNTHETIC biochar kiln demo. "
         "Use only facts given. Do not state any number not present in the facts. No carbon-credit claims."},
        {"role": "user", "content": "Write a 3-5 sentence operations summary.\nFacts: " + json.dumps(facts)}],
        agent="reporting", max_tokens=400).strip()
    ss = b["sensor_summary"]
    yld = b["output_mass_kg"] / b["input_mass_kg"] * 100 if b["input_mass_kg"] else float("nan")
    L = [f"# Batch report {batch_id}", "", f"> **{REPORT_BANNER}**  ", f"> **{SYNTHETIC_BANNER}.** "
         "`synthetic: true`. Not for MRV, certification or carbon-credit use.", "",
         "## Batch facts (from SQL)", "| field | value |", "|---|---|",
         f"| batch_id | {batch_id} |", f"| feedstock | {b['feedstock']} |", f"| start | {iso(b['start_ts'])} |",
         f"| end | {iso(b['end_ts'])} |", f"| duration | {b['duration_min']} min |",
         f"| input mass | {b['input_mass_kg']:.2f} kg |", f"| output mass (last reading) | {b['output_mass_kg']:.2f} kg |",
         f"| mass yield (output/input) | {yld:.1f} % |", f"| data sources | {', '.join(b['sources'])} |",
         f"| seed / injected faults | {b['seed']} / {json.dumps(b['faults_injected'])} |", "",
         "## Sensor summary (from SQL)", "| sensor | n | min | mean | max |", "|---|---|---|---|---|"]
    for k, v in sorted(ss.items()):
        L.append(f"| {k} | {v['n']} | {v['min']:.2f} | {v['mean']:.2f} | {v['max']:.2f} |")
    L += ["", f"## Anomalies ({len(an)})", "| # | rule | sensor | start | end | samples | peak | threshold | severity |",
          "|---|---|---|---|---|---|---|---|---|"]
    for i, a in enumerate(an, 1):
        L.append(f"| {i} | {a['rule']} | {a['sensor']} | {iso(a['ts'])} | {iso(a['end_ts'])} | {a['samples']} | "
                 f"{a['value']:.2f} | {a['threshold']} | {a['severity']} |")
    L += ["", "## Diagnoses (LLM, unverified)"]
    seen = {}
    for a in an:
        for d in a["diagnoses"]:
            seen.setdefault((d["explanation"], d["suggested_action"], d["model"]), []).append(a["rule"])
    for (ex, act, model), rules in seen.items():
        L += [f"- **{', '.join(rules)}** ({model}): {ex}  ", f"  *Suggested action:* {act}"]
    L += ["", f"## Narrative (LLM: {llm.model}, unverified)", narrative, "",
          "---", f"*{REPORT_BANNER}. Generated by KilnMCP from {SYNTHETIC_BANNER.lower()}. "
          "Numbers in tables come from SQLite; only the narrative and diagnoses are LLM text.*", ""]
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    path = str(Path(out_dir) / f"batch_{batch_id}.md")
    Path(path).write_text("\n".join(L), encoding="utf-8")
    await call(s, "save_report", batch_id=batch_id, path=path, model=llm.model)
    return path
