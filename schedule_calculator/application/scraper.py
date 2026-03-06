from __future__ import annotations

import logging

from schedule_calculator.application.interfaces import PortalClient
from schedule_calculator.domain.models import PortalCredentials, ScrapedGroup
from schedule_calculator.domain.rules import unique_preserve_order


class ScraperService:
    def __init__(
        self,
        client: PortalClient,
        logger: logging.Logger | None = None,
    ) -> None:
        self.client = client
        self.logger = logger or logging.getLogger(__name__)

    def scrape_subjects(
        self,
        subject_ids: list[str],
        credentials: PortalCredentials,
    ) -> list[ScrapedGroup]:
        unique_subject_ids = [subject_id for subject_id in unique_preserve_order(subject_ids) if subject_id]
        self.client.authenticate(credentials)

        groups: list[ScrapedGroup] = []
        for subject_id in unique_subject_ids:
            subject_groups = self.client.fetch_groups_for_subject(subject_id)
            self.logger.info(
                "Subject %s: scraped %s groups.",
                subject_id,
                len(subject_groups),
            )
            groups.extend(subject_groups)
        return groups

