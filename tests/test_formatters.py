from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from schedule_calculator.domain.models import CandidateEnrollment, SessionRecord
from schedule_calculator.errors import ValidationError
from schedule_calculator.formatters import format_enrollment_label, read_scraped_groups


class FormatterTests(unittest.TestCase):
    def test_read_scraped_groups_rejects_non_object_entries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            payload_path = Path(temp_dir) / "groups.json"
            payload_path.write_text('["invalid"]\n', encoding="utf-8")

            with self.assertRaises(ValidationError) as context:
                read_scraped_groups(payload_path)

            self.assertEqual(str(context.exception), "Group entry #1 must be a JSON object.")

    def test_read_scraped_groups_redacts_low_level_parse_errors(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            payload_path = Path(temp_dir) / "groups.json"
            payload_path.write_text(
                (
                    '[{"header": {"group_code": "1IL131", "province": "PANAMÁ"}, '
                    '"sessions": ["bad-session"], "subject_professors": []}]\n'
                ),
                encoding="utf-8",
            )

            with self.assertRaises(ValidationError) as context:
                read_scraped_groups(payload_path)

            self.assertEqual(str(context.exception), "Group entry #1 is malformed.")

    def test_format_enrollment_label_includes_codhora_and_lab(self) -> None:
        enrollment = CandidateEnrollment(
            group_code="1SF242",
            subject_id="0698",
            province="PANAMÁ",
            sessions=[
                SessionRecord(
                    day="MONDAY",
                    subject="",
                    session_type="Laboratory",
                    classroom="VVIRT",
                    lab_code="L",
                )
            ],
            subject_name="GEST. INFORM.",
            hour_code="742",
        )

        label = format_enrollment_label(enrollment, include_subject_name=True)

        self.assertEqual(
            label,
            "0698 GEST. INFORM.:1SF242 (CODHORA: 742, Lab: L)",
        )


if __name__ == "__main__":
    unittest.main()
