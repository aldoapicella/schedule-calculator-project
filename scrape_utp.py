from __future__ import annotations

import argparse
import logging
import sys

from schedule_calculator.application.scraper import ScraperService
from schedule_calculator.errors import ConfigurationError, ScheduleCalculatorError
from schedule_calculator.formatters import default_scrape_output_path, write_scraped_groups
from schedule_calculator.infrastructure.config import (
    load_portal_base_url,
    load_portal_credentials,
)
from schedule_calculator.infrastructure.logging import configure_logging, log_exception_summary
from schedule_calculator.infrastructure.utp_portal import UTPPortalClient


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("group concurrency must be at least 1")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Scrape UTP schedule data by subject.")
    parser.add_argument(
        "--subject-ids",
        required=True,
        help="Comma-separated subject IDs to scrape.",
    )
    parser.add_argument(
        "--output",
        default=str(default_scrape_output_path()),
        help="Output JSON path.",
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
    parser.add_argument(
        "--group-concurrency",
        type=_positive_int,
        default=6,
        help="Parallel detail-page workers per subject.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    configure_logging(args.log_file, verbose=args.verbose)
    logger = logging.getLogger(__name__)

    try:
        credentials = load_portal_credentials(args.env_file)
        base_url = load_portal_base_url(args.env_file)
        subject_ids = [item.strip() for item in args.subject_ids.split(",") if item.strip()]
        if not subject_ids:
            raise ValueError("At least one subject ID is required.")

        client = UTPPortalClient(
            base_url=base_url,
            logger=logger,
            group_concurrency=args.group_concurrency,
        )
        service = ScraperService(client, logger=logger)
        groups = service.scrape_subjects(subject_ids, credentials)
        write_scraped_groups(groups, args.output)
    except ConfigurationError as exc:
        log_exception_summary(logger, exc, verbose=args.verbose)
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        log_exception_summary(logger, exc, verbose=args.verbose)
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except ScheduleCalculatorError as exc:
        log_exception_summary(logger, exc, verbose=args.verbose)
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        log_exception_summary(logger, exc, verbose=args.verbose)
        print("Error: unexpected scraper failure.", file=sys.stderr)
        return 1

    logger.info("Saved %s groups to %s", len(groups), args.output)
    print(f"Saved {len(groups)} groups to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
