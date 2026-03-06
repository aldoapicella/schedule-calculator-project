from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from schedule_calculator.errors import ValidationError
from schedule_calculator.formatters import read_scraped_groups


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


if __name__ == "__main__":
    unittest.main()
