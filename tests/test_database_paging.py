import database

class FakeQuery:
    def __init__(self, data): self.data_all = data; self.rng = None
    def range(self, a, b): self.rng = (a, b); return self
    def execute(self):
        a, b = self.rng
        return type("R", (), {"data": self.data_all[a:b + 1]})()

def test_fetch_all_pages_until_short_page():
    rows = list(range(2500))
    calls = []
    def build():
        calls.append(1); return FakeQuery(rows)
    assert database.fetch_all(build, page=1000) == rows
    assert len(calls) == 3

def test_chunks():
    assert database.chunks(["a", "b", "c"], 2) == [["a", "b"], ["c"]]

def test_search_strips_specials_and_empty(monkeypatch):
    monkeypatch.setattr(database, "get_client", lambda: (_ for _ in ()).throw(AssertionError("不應查詢")))
    assert database.search_companies("  ,()*% ") == []
