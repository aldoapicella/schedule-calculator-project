from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from schedule_calculator.application.scheduler import SchedulerService
from schedule_calculator.domain.models import ScheduleRequest
from schedule_calculator.errors import ConfigurationError, ScheduleCalculatorError
from schedule_calculator.formatters import format_schedule_summary
from schedule_calculator.infrastructure.config import load_database_config
from schedule_calculator.infrastructure.logging import configure_logging, log_exception_summary
from schedule_calculator.infrastructure.postgres import (
    PostgresGroupCatalogRepository,
    postgres_connection,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Calculate the best subject schedule.")
    parser.add_argument("--subjects", required=True, help="Comma-separated desired subject IDs.")
    parser.add_argument(
        "--required-subjects",
        default="",
        help="Comma-separated required subject IDs.",
    )
    parser.add_argument(
        "--available-start",
        required=True,
        help="Available start time in HH:MM format.",
    )
    parser.add_argument(
        "--available-end",
        required=True,
        help="Available end time in HH:MM format.",
    )
    parser.add_argument(
        "--province",
        required=True,
        help="Desired province for physical classes.",
    )
    parser.add_argument(
        "--log-file",
        default=None,
        help="Optional log file path.",
    )
    parser.add_argument(
        "--env-file",
        default=None,
        help="Optional path to a .env file.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose debug logging.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    configure_logging(args.log_file, verbose=args.verbose)
    logger = logging.getLogger(__name__)
    try:
        database_config = load_database_config(args.env_file)
        request = ScheduleRequest(
            desired_subjects=_parse_csv(args.subjects),
            required_subjects=_parse_csv(args.required_subjects),
            available_start=_parse_time(args.available_start),
            available_end=_parse_time(args.available_end),
            desired_province=args.province.strip(),
        )

        with postgres_connection(database_config) as connection:
            service = SchedulerService(PostgresGroupCatalogRepository(connection))
            result = service.find_best_schedule(request)
    except (ConfigurationError, ValueError) as exc:
        log_exception_summary(logger, exc, verbose=args.verbose)
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except ScheduleCalculatorError as exc:
        log_exception_summary(logger, exc, verbose=args.verbose)
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        log_exception_summary(logger, exc, verbose=args.verbose)
        print("Error: unexpected calculator failure.", file=sys.stderr)
        return 1

    print(format_schedule_summary(result))
    return 0


def _parse_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _parse_time(value: str):
    return datetime.strptime(value, "%H:%M").time()


if __name__ == "__main__":
    raise SystemExit(main())
