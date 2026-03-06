from __future__ import annotations

import json
from pathlib import Path

from schedule_calculator.application.importer import ImportResult
from schedule_calculator.domain.models import CandidateEnrollment, ScheduleResult, ScrapedGroup


def write_scraped_groups(groups: list[ScrapedGroup], output_path: str | Path) -> None:
    path = Path(output_path)
    path.write_text(
        json.dumps([group.to_dict() for group in groups], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def read_scraped_groups(input_path: str | Path) -> list[ScrapedGroup]:
    path = Path(input_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("Input JSON must be an array of groups.")
    return [ScrapedGroup.from_dict(item) for item in payload]


def format_schedule_summary(result: ScheduleResult | None) -> str:
    if result is None:
        return "No valid schedule found."
    return "Schedule found!\nChosen enrollments: " + ", ".join(
        _format_enrollment(enrollment) for enrollment in result.chosen_enrollments
    )


def format_import_summary(result: ImportResult) -> str:
    return (
        f"Processed: {result.processed_count}, "
        f"Skipped: {result.skipped_count}, "
        f"Failed: {result.failed_count}"
    )


def _format_enrollment(enrollment: CandidateEnrollment) -> str:
    lab_codes = {
        session.lab_code
        for session in enrollment.sessions
        if session.session_type.lower() == "laboratory" and session.lab_code
    }
    if lab_codes:
        return (
            f"{enrollment.subject_id}:{enrollment.group_code} "
            f"(Lab: {', '.join(sorted(lab_codes))})"
        )
    return f"{enrollment.subject_id}:{enrollment.group_code}"
