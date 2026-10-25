import socket

import pytest

import serve


def test_port_available_false_when_bound():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen(1)
    try:
        assert serve.port_available(s.getsockname()[1]) is False
    finally:
        s.close()


def test_port_available_true_when_free():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    assert serve.port_available(port) is True


def test_get_port_default_8765(monkeypatch):
    monkeypatch.setattr(serve, "load_dotenv", lambda *a, **k: None)
    monkeypatch.delenv("APP_PORT", raising=False)
    assert serve.get_port() == 8765


def test_get_port_reads_env(monkeypatch):
    monkeypatch.setattr(serve, "load_dotenv", lambda *a, **k: None)
    monkeypatch.setenv("APP_PORT", "9001")
    assert serve.get_port() == 9001


def test_get_port_rejects_5000(monkeypatch):
    monkeypatch.setattr(serve, "load_dotenv", lambda *a, **k: None)
    monkeypatch.setenv("APP_PORT", "5000")
    with pytest.raises(ValueError):
        serve.get_port()


def test_get_port_rejects_non_integer(monkeypatch):
    monkeypatch.setattr(serve, "load_dotenv", lambda *a, **k: None)
    monkeypatch.setenv("APP_PORT", "abc")
    with pytest.raises(ValueError):
        serve.get_port()


def _no_logs(monkeypatch):
    monkeypatch.setattr(serve, "setup_logging", lambda *a, **k: None)


def test_main_exits_1_when_port_busy(monkeypatch):
    _no_logs(monkeypatch)
    called = []
    monkeypatch.setattr(serve.waitress, "serve", lambda *a, **k: called.append(1))
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen(1)
    monkeypatch.setattr(serve, "get_port", lambda: s.getsockname()[1])
    try:
        assert serve.main() == 1
    finally:
        s.close()
    assert called == []


def test_main_exits_1_on_bad_port(monkeypatch):
    _no_logs(monkeypatch)
    called = []
    monkeypatch.setattr(serve.waitress, "serve", lambda *a, **k: called.append(1))

    def boom():
        raise ValueError("bad")
    monkeypatch.setattr(serve, "get_port", boom)
    assert serve.main() == 1
    assert called == []


def test_main_serves_on_loopback(monkeypatch):
    _no_logs(monkeypatch)
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    monkeypatch.setattr(serve, "get_port", lambda: port)
    calls = []
    monkeypatch.setattr(serve.waitress, "serve",
                        lambda app, **k: calls.append((app, k)))
    assert serve.main() == 0
    assert calls[0][1] == {"host": "127.0.0.1", "port": port}
