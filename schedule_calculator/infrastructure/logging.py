from __future__ import annotations

import logging
from pathlib import Path


def configure_logging(log_file: str | Path | None = None, level: int = logging.INFO) -> None:
    handlers: list[logging.Handler]
    if log_file:
        path = Path(log_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        handlers = [logging.FileHandler(path, encoding="utf-8")]
    else:
        handlers = [logging.StreamHandler()]

    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=handlers,
        force=True,
    )

