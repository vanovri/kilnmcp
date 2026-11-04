"""OpenAI-compatible chat client (TokenMeter proxy -> 9Router) and a deterministic fake for tests.

The API key is read from NINEROUTER_API_KEY and only ever placed in the Authorization header.
If unset, no Authorization header is sent and the TokenMeter proxy applies its own fallback.
"""
from __future__ import annotations
import json, os, re, time
import httpx

DEFAULT_BASE = "http://127.0.0.1:8787/p/kilnmcp/v1"
DEFAULT_MODEL = "xai/grok-code-fast-1"

class LLM:
    def __init__(self, base_url: str | None = None, model: str | None = None, timeout: float = 120):
        self.base_url = (base_url or os.environ.get("KILNMCP_LLM_BASE_URL", DEFAULT_BASE)).rstrip("/")
        self.model = model or os.environ.get("KILNMCP_MODEL", DEFAULT_MODEL)
        self.timeout = timeout
        self.calls: list[dict] = []

    def chat(self, messages: list[dict], agent: str, max_tokens: int = 600) -> str:
        headers = {"Content-Type": "application/json", "X-TokenMeter-Tag": "kilnmcp",
                   "X-TokenMeter-Tags": f"agent={agent}"}
        key = os.environ.get("NINEROUTER_API_KEY")
        if key:
            headers["Authorization"] = f"Bearer {key}"
        body = {"model": self.model, "messages": messages, "max_tokens": max_tokens, "temperature": 0.2}
        body["stream"] = False
        for attempt in (1, 2):
            t = time.perf_counter()
            r = httpx.post(f"{self.base_url}/chat/completions", json=body, headers=headers, timeout=self.timeout)
            ms = (time.perf_counter() - t) * 1000
            if r.status_code != 200:
                self.calls.append({"agent": agent, "ms": round(ms, 1), "status": r.status_code})
                if attempt == 2:
                    raise RuntimeError(f"LLM HTTP {r.status_code}: {r.text[:300]}")
                continue
            try:  # tolerate trailing bytes after the JSON object (seen once from upstream)
                j, end = json.JSONDecoder().raw_decode(r.text.lstrip())
                if r.text.lstrip()[end:].strip():
                    self.calls.append({"agent": agent, "note": "trailing bytes after JSON ignored"})
                break
            except json.JSONDecodeError:
                self.calls.append({"agent": agent, "ms": round(ms, 1), "status": "bad_json"})
                if attempt == 2:
                    raise
        u = j.get("usage") or {}
        self.calls.append({"agent": agent, "ms": round(ms, 1), "status": 200, "model": j.get("model", self.model),
                           "attempt": attempt, "prompt_tokens": u.get("prompt_tokens"),
                           "completion_tokens": u.get("completion_tokens"), "total_tokens": u.get("total_tokens"),
                           "reasoning_tokens": (u.get("completion_tokens_details") or {}).get("reasoning_tokens")})
        return j["choices"][0]["message"]["content"] or ""

class FakeLLM(LLM):
    """Canned, deterministic responses (tests / --mock-llm). No network."""
    def __init__(self):
        self.model = "fake/mock-llm"; self.calls = []; self.base_url = "mock://"

    def chat(self, messages, agent, max_tokens=600):
        text = messages[-1]["content"]
        if agent == "diagnosis":
            cause = (
                "air_leak" if "R-O2-HIGH" in text else
                ("wet_feedstock" if "R-MOIST-HIGH" in text else
                 ("sensor_fault" if "STUCK" in text else "other"))
            )
            out = json.dumps({"explanation": f"[MOCK] Pattern consistent with {cause} based on the supplied windows.",
                              "suggested_action": "[MOCK] Inspect seals/door gaskets and feedstock moisture before next batch.",
                              "probable_cause": cause})
        else:
            out = "[MOCK] Batch ran through heat-up, steady pyrolysis and cool-down; anomalies listed below were flagged by rules and diagnosed."
        self.calls.append({"agent": agent, "ms": 0.0, "status": 200, "model": self.model,
                           "prompt_tokens": len(text) // 4, "completion_tokens": len(out) // 4})
        return out

def parse_json(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    return {"explanation": text.strip()[:1200], "suggested_action": "", "probable_cause": "other"}
