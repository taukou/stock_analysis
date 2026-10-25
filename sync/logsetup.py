"""紀錄設定：logs/{name}.log 每日輪替保留 30 天，並輸出到主控台。"""
import logging
import sys
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

_MARK = "_sync_handler"
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def setup_logging(name: str, base_dir: Path | None = None) -> logging.Logger:
    base = Path(base_dir) if base_dir else _PROJECT_ROOT
    log_dir = base / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for h in list(root.handlers):
        if getattr(h, _MARK, False):
            root.removeHandler(h)
            h.close()

    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    fh = TimedRotatingFileHandler(log_dir / f"{name}.log", when="midnight",
                                  backupCount=30, encoding="utf-8")
    fh.setFormatter(fmt)
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    for h in (fh, ch):
        setattr(h, _MARK, True)
        root.addHandler(h)
    return logging.getLogger(name)
