import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest


@pytest.fixture(autouse=True)
def _isolate_ai_picks(monkeypatch, tmp_path):
    """測試不讀真的 .env 金鑰、不碰 reports/ai_picks。"""
    import ai_picks
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    monkeypatch.setattr(ai_picks, "PICKS_DIR", tmp_path / "ai_picks")
