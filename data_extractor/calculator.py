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
from schedule_calculator.formatters import format_schedule_summary
from schedule_calculator.infrastructure.config import load_database_config
from schedule_calculator.infrastructure.logging import configure_logging
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
        default="schedule.log",
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

    configure_logging(args.log_file, level=logging.DEBUG)
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

    if result is not None:
        logging.info("Schedule found!")
        logging.info(
            "Chosen enrollments: %s",
            ", ".join(
                f"{enrollment.subject_id}:{enrollment.group_code}"
                for enrollment in result.chosen_enrollments
            ),
        )
        for session in result.final_schedule:
            start_time = session.start_time.strftime("%H:%M") if session.start_time else "?"
            end_time = session.end_time.strftime("%H:%M") if session.end_time else "?"
            logging.info(
                "%s %s - %s in %s (%s)",
                session.day,
                start_time,
                end_time,
                session.classroom,
                session.session_type,
            )
    else:
        logging.info("No valid schedule found.")

    print(format_schedule_summary(result))
    return 0


def _parse_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _parse_time(value: str):
    return datetime.strptime(value, "%H:%M").time()


if __name__ == "__main__":
    raise SystemExit(main())
