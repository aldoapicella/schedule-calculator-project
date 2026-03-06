from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from schedule_calculator.application.importer import ImportService
from schedule_calculator.formatters import format_import_summary, read_scraped_groups
from schedule_calculator.infrastructure.config import load_database_config
from schedule_calculator.infrastructure.logging import configure_logging
from schedule_calculator.infrastructure.postgres import (
    PostgresGroupPersistenceRepository,
    postgres_connection,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Insert scraped schedule data into Postgres.")
    parser.add_argument("--input", required=True, help="Path to the scraper JSON payload.")
    parser.add_argument(
        "--log-file",
        default="insertion.log",
        help="Optional log file path.",
    )
    parser.add_argument(
        "--env-file",
        default=None,
        help="Optional path to a .env file.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    configure_logging(args.log_file, level=logging.INFO)
    groups = read_scraped_groups(args.input)
    database_config = load_database_config(args.env_file)

    with postgres_connection(database_config) as connection:
        service = ImportService(PostgresGroupPersistenceRepository(connection))
        result = service.import_groups(groups)

    print(format_import_summary(result))
    return 0 if result.failed_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
