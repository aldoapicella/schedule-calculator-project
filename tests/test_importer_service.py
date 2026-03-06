from __future__ import annotations

import unittest

from schedule_calculator.application.importer import ImportService
from schedule_calculator.domain.models import GroupHeader, ScrapedGroup, SessionRecord, SubjectProfessor


class FakePersistenceRepository:
    def __init__(
        self,
        *,
        processed: set[str] | None = None,
        raise_on_persist: Exception | None = None,
    ) -> None:
        self.processed = processed or set()
        self.raise_on_persist = raise_on_persist
        self.persisted: list[ScrapedGroup] = []
        self.checked_group_codes: list[str] = []

    def is_group_processed(self, group_code: str) -> bool:
        self.checked_group_codes.append(group_code)
        return group_code in self.processed

    def persist_group(self, group: ScrapedGroup) -> None:
        if self.raise_on_persist:
            raise self.raise_on_persist
        self.persisted.append(group)


class ImportServiceTests(unittest.TestCase):
    def test_empty_payload_returns_zero_counts(self) -> None:
        repository = FakePersistenceRepository()
        service = ImportService(repository)

        result = service.import_groups([])

        self.assertEqual(result.processed_count, 0)
        self.assertEqual(result.skipped_count, 0)
        self.assertEqual(result.failed_count, 0)
        self.assertEqual(repository.persisted, [])

    def test_missing_group_code_fails_validation(self) -> None:
        repository = FakePersistenceRepository()
        service = ImportService(repository)

        result = service.import_groups([self._valid_group(group_code="")])

        self.assertEqual(result.failed_count, 1)
        self.assertIn("<missing-group-code>", result.errors)
        self.assertEqual(repository.persisted, [])

    def test_invalid_province_fails_validation(self) -> None:
        repository = FakePersistenceRepository()
        service = ImportService(repository)

        result = service.import_groups([self._valid_group(province="MARS")])

        self.assertEqual(result.failed_count, 1)
        self.assertIn("Province 'MARS' is not allowed", result.errors["G1"])
        self.assertEqual(repository.persisted, [])

    def test_missing_subject_mapping_fails_validation(self) -> None:
        repository = FakePersistenceRepository()
        service = ImportService(repository)
        group = self._valid_group()
        group.subject_professors = []

        result = service.import_groups([group])

        self.assertEqual(result.failed_count, 1)
        self.assertIn("No mapping found for subject", result.errors["G1"])
        self.assertEqual(repository.persisted, [])

    def test_professor_less_subject_is_allowed(self) -> None:
        repository = FakePersistenceRepository()
        service = ImportService(repository)
        group = self._valid_group(
            professor_name="",
            professor_email="",
        )

        result = service.import_groups([group])

        self.assertEqual(result.processed_count, 1)
        self.assertEqual(result.failed_count, 0)
        self.assertEqual(repository.persisted, [group])

    def test_repository_error_is_reported_as_failure(self) -> None:
        repository = FakePersistenceRepository(raise_on_persist=RuntimeError("db down"))
        service = ImportService(repository)

        result = service.import_groups([self._valid_group()])

        self.assertEqual(result.failed_count, 1)
        self.assertEqual(result.errors["G1"], "db down")
        self.assertEqual(repository.persisted, [])

    def test_already_processed_group_is_skipped(self) -> None:
        repository = FakePersistenceRepository(processed={"G1"})
        service = ImportService(repository)

        result = service.import_groups([self._valid_group()])

        self.assertEqual(result.skipped_count, 1)
        self.assertEqual(result.processed_count, 0)
        self.assertEqual(repository.checked_group_codes, ["G1"])
        self.assertEqual(repository.persisted, [])

    @staticmethod
    def _valid_group(
        *,
        group_code: str = "G1",
        province: str = "PANAMÁ",
        professor_name: str = "Ada Lovelace",
        professor_email: str = "ada@example.com",
    ) -> ScrapedGroup:
        return ScrapedGroup(
            header=GroupHeader(
                group_code=group_code,
                province=province,
                faculty="Engineering",
                year="2025",
                period="1",
            ),
            sessions=[
                SessionRecord(
                    day="MONDAY",
                    subject="FISICA II(A )",
                    session_type="Theory",
                    classroom="AULA 1",
                    time_slot="7:50-8:35A.M.",
                )
            ],
            subject_professors=[
                SubjectProfessor(
                    subject="FISICA II(A )",
                    subject_code="0698",
                    professor_name=professor_name,
                    professor_email=professor_email,
                )
            ],
        )


if __name__ == "__main__":
    unittest.main()
