from __future__ import annotations

import argparse
import logging

from schedule_calculator.application.scraper import ScraperService
from schedule_calculator.formatters import write_scraped_groups
from schedule_calculator.infrastructure.config import (
    load_portal_base_url,
    load_portal_credentials,
)
from schedule_calculator.infrastructure.logging import configure_logging
from schedule_calculator.infrastructure.utp_portal import UTPPortalClient


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Scrape UTP schedule data by subject.")
    parser.add_argument(
        "--subject-ids",
        required=True,
        help="Comma-separated subject IDs to scrape.",
    )
    parser.add_argument(
        "--output",
        default="outputs.json",
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
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    configure_logging(args.log_file, level=logging.INFO)
    credentials = load_portal_credentials(args.env_file)
    base_url = load_portal_base_url(args.env_file)
    subject_ids = [item.strip() for item in args.subject_ids.split(",") if item.strip()]

    client = UTPPortalClient(base_url=base_url)
    service = ScraperService(client)
    groups = service.scrape_subjects(subject_ids, credentials)
    write_scraped_groups(groups, args.output)

    logging.info("Saved %s groups to %s", len(groups), args.output)
    print(f"Saved {len(groups)} groups to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
