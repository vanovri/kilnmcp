import json, httpx
from kilnmcp.llm import LLM, parse_json

def test_auth_header_from_env_and_tags(monkeypatch):
    seen = {}
    def fake_post(url, json=None, headers=None, timeout=None):
        seen.update(url=url, headers=headers, body=json)
        return httpx.Response(200, json={"model": "m", "choices": [{"message": {"content": "hi"}}],
                                         "usage": {"prompt_tokens": 3, "completion_tokens": 1}})
    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.setenv("NINEROUTER_API_KEY", "sk-test-secret")
    llm = LLM(base_url="http://x/p/kilnmcp/v1")
    assert llm.chat([{"role": "user", "content": "q"}], agent="diagnosis") == "hi"
    assert seen["url"] == "http://x/p/kilnmcp/v1/chat/completions"
    assert seen["headers"]["Authorization"] == "Bearer sk-test-secret"
    assert seen["headers"]["X-TokenMeter-Tags"] == "agent=diagnosis"
    assert "sk-test-secret" not in str(llm.calls)
    monkeypatch.delenv("NINEROUTER_API_KEY")
    llm.chat([{"role": "user", "content": "q"}], agent="reporting")
    assert "Authorization" not in seen["headers"]

def test_parse_json():
    assert parse_json('```json\n{"explanation":"a","suggested_action":"b"}\n```')["explanation"] == "a"
    assert parse_json("plain text")["explanation"] == "plain text"

def test_trailing_bytes_tolerated(monkeypatch):
    body = '{"model":"m","choices":[{"message":{"content":"ok"}}],"usage":{}}\n{"x":1}'
    monkeypatch.setattr(httpx, "post", lambda *a, **k: httpx.Response(200, text=body))
    assert LLM(base_url="http://x").chat([{"role": "user", "content": "q"}], agent="t") == "ok"
