import os, sys, pytest
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

@pytest.fixture
def dbpath(tmp_path, monkeypatch):
    p = str(tmp_path / "kiln.db")
    monkeypatch.setenv("KILNMCP_DB", p)
    monkeypatch.chdir(ROOT)
    return p
