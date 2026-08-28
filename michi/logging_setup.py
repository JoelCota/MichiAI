"""Console + rotating file logging."""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

from .config import PROJECT_ROOT, Config

_CONFIGURED = False


def setup_logging(cfg: Config) -> logging.Logger:
    global _CONFIGURED
    logger = logging.getLogger("michi")
    if _CONFIGURED:
        return logger

    level = getattr(logging, str(cfg.get("logging.level", "INFO")).upper(), logging.INFO)
    logger.setLevel(level)
    logger.propagate = False

    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter("%(asctime)s  %(message)s", datefmt="%H:%M:%S"))
    console.setLevel(level)
    logger.addHandler(console)

    log_file = cfg.get("logging.file")
    if log_file:
        path = Path(log_file)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            path, maxBytes=2_000_000, backupCount=3, encoding="utf-8"
        )
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s  %(levelname)-7s %(name)s  %(message)s")
        )
        logger.addHandler(file_handler)

    # Quieten noisy dependencies.
    for noisy in ("httpx", "httpcore", "urllib3", "faster_whisper", "openai", "anthropic"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _CONFIGURED = True
    return logger


def get_logger(name: str = "michi") -> logging.Logger:
    return logging.getLogger(name if name.startswith("michi") else f"michi.{name}")
