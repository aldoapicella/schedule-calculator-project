from __future__ import annotations

import logging
from dataclasses import dataclass, field

from schedule_calculator.application.interfaces import GroupPersistenceRepository
from schedule_calculator.domain.models import ScrapedGroup
from schedule_calculator.domain.rules import ensure_allowed_province, normalize_subject, parse_time_slot


@dataclass(slots=True)
class ImportResult:
    processed_count: int = 0
    skipped_count: int = 0
    failed_count: int = 0
    errors: dict[str, str] = field(default_factory=dict)


class ImportService:
    def __init__(
        self,
        repository: GroupPersistenceRepository,
        logger: logging.Logger | None = None,
    ) -> None:
        self.repository = repository
        self.logger = logger or logging.getLogger(__name__)

    def import_groups(self, groups: list[ScrapedGroup]) -> ImportResult:
        result = ImportResult()
        for group in groups:
            group_code = group.header.group_code or "<missing-group-code>"
            try:
                self._validate_group(group)
                if self.repository.is_group_processed(group.header.group_code):
                    result.skipped_count += 1
                    self.logger.info("Group %s: Already processed. Skipping.", group.header.group_code)
                    continue
                self.repository.persist_group(group)
                result.processed_count += 1
            except Exception as exc:
                result.failed_count += 1
                result.errors[group_code] = str(exc)
                self.logger.error("Group %s: Error processing group: %s", group_code, exc)
        return result

    def _validate_group(self, group: ScrapedGroup) -> None:
        if not group.header.group_code:
            raise ValueError("Header is missing group_code.")
        ensure_allowed_province(group.header.province)

        subject_mapping = {
            normalize_subject(subject_professor.subject): subject_professor.subject_code
            for subject_professor in group.subject_professors
            if subject_professor.subject_code
        }

        for session in group.sessions:
            if not (
                session.day
                and session.time_slot
                and session.subject
                and session.session_type
                and session.classroom
            ):
                raise ValueError(f"Group {group.header.group_code}: Incomplete session data: {session}")
            parse_time_slot(session.time_slot)
            normalized_subject = normalize_subject(session.subject)
            if normalized_subject not in subject_mapping:
                raise ValueError(
                    f"Group {group.header.group_code}: No mapping found for subject "
                    f"'{normalized_subject}' in session: {session}"
                )

