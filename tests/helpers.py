import json
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str):
    """讀取 tests/fixtures/<name>（UTF-8 JSON）。"""
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))
