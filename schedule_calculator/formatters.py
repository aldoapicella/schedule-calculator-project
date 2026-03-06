from __future__ import annotations

import json
from pathlib import Path

from schedule_calculator.application.importer import ImportResult
from schedule_calculator.domain.models import CandidateEnrollment, ScheduleResult, ScrapedGroup
from schedule_calculator.errors import ValidationError

ARTIFACTS_DIR = Path("artifacts")


def write_scraped_groups(groups: list[ScrapedGroup], output_path: str | Path) -> None:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps([group.to_dict() for group in groups], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def read_scraped_groups(input_path: str | Path) -> list[ScrapedGroup]:
    path = Path(input_path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValidationError(f"Input JSON file was not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValidationError(f"Input JSON is invalid: {path}") from exc
    if not isinstance(payload, list):
        raise ValidationError("Input JSON must be an array of groups.")
    groups: list[ScrapedGroup] = []
    for index, item in enumerate(payload, start=1):
        if not isinstance(item, dict):
            raise ValidationError(f"Group entry #{index} must be a JSON object.")
        try:
            groups.append(ScrapedGroup.from_dict(item))
        except (TypeError, ValueError, AttributeError, KeyError) as exc:
            raise ValidationError(f"Group entry #{index} is malformed.") from exc
    return groups


def format_schedule_summary(result: ScheduleResult | None) -> str:
    if result is None:
        return "No valid schedule found."
    return "Schedule found!\nChosen enrollments: " + ", ".join(
        format_enrollment_label(enrollment) for enrollment in result.chosen_enrollments
    )


def format_import_summary(result: ImportResult) -> str:
    return (
        f"Processed: {result.processed_count}, "
        f"Skipped: {result.skipped_count}, "
        f"Failed: {result.failed_count}"
    )


def default_scrape_output_path() -> Path:
    return ARTIFACTS_DIR / "scraped_groups.json"


def format_enrollment_label(
    enrollment: CandidateEnrollment,
    *,
    include_subject_name: bool = False,
) -> str:
    lab_codes = {
        session.lab_code
        for session in enrollment.sessions
        if session.session_type.lower() == "laboratory" and session.lab_code
    }
    subject_label = enrollment.subject_id
    if include_subject_name and enrollment.subject_name:
        subject_label = f"{enrollment.subject_id} {enrollment.subject_name}"
    if lab_codes:
        return (
            f"{subject_label}:{enrollment.group_code} "
            f"(Lab: {', '.join(sorted(lab_codes))})"
        )
    return f"{subject_label}:{enrollment.group_code}"
