from __future__ import annotations

import logging
from pathlib import Path


def configure_logging(
    log_file: str | Path | None = None,
    *,
    verbose: bool = False,
) -> None:
    handlers: list[logging.Handler]
    if log_file:
        path = Path(log_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        handlers = [logging.FileHandler(path, encoding="utf-8")]
    else:
        handlers = [logging.StreamHandler()]

    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=handlers,
        force=True,
    )
    logging.captureWarnings(True)


def log_exception_summary(
    logger: logging.Logger,
    exc: BaseException,
    *,
    verbose: bool = False,
    level: int = logging.ERROR,
) -> None:
    logger.log(level, "%s", exc)
    if verbose:
        logger.debug("Detailed exception information follows.", exc_info=exc)
