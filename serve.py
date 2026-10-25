"""背景啟動網站：waitress 綁 127.0.0.1，埠號讀 APP_PORT（預設 8765，禁用 5000）。"""
import logging
import os
import socket
import sys
from pathlib import Path

import waitress
from dotenv import load_dotenv

from app import app
from sync.logsetup import setup_logging

HOST = "127.0.0.1"
DEFAULT_PORT = 8765
LOG_ROOT = Path(__file__).resolve().parent
log = logging.getLogger("web")


def get_port() -> int:
    load_dotenv(LOG_ROOT / ".env")
    raw = os.getenv("APP_PORT", "").strip() or str(DEFAULT_PORT)
    try:
        port = int(raw)
    except ValueError:
        raise ValueError(f"APP_PORT 不是整數: {raw!r}")
    if port == 5000:
        raise ValueError("APP_PORT 不得為 5000")
    if not 1 <= port <= 65535:
        raise ValueError(f"APP_PORT 超出範圍: {port}")
    return port


def port_available(port: int, host: str = HOST) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind((host, port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def main() -> int:
    setup_logging("web", base_dir=LOG_ROOT)
    try:
        port = get_port()
    except ValueError as e:
        log.error("埠號設定錯誤: %s", e)
        return 1
    if not port_available(port):
        log.error("埠 %s 已被佔用，不改用其他埠，結束", port)
        return 1
    log.info("網站啟動 http://%s:%s/", HOST, port)
    waitress.serve(app, host=HOST, port=port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
