from __future__ import annotations

import unittest
from datetime import time

from schedule_calculator.application.scheduler import SchedulerService
from schedule_calculator.domain.models import CourseGroup, ScheduleRequest, SessionRecord


class FakeCatalogRepository:
    def __init__(self, groups_by_subject: dict[str, list[CourseGroup]]) -> None:
        self.groups_by_subject = groups_by_subject
        self.calls: list[str] = []

    def list_groups_for_subject(self, subject_id: str) -> list[CourseGroup]:
        self.calls.append(subject_id)
        return list(self.groups_by_subject.get(subject_id, []))


class SchedulerServiceTests(unittest.TestCase):
    def test_dedupes_desired_subjects_before_querying_repository(self) -> None:
        repository = FakeCatalogRepository(
            {
                "MAT": [self._group("GMAT", "MAT", "PANAMÁ", [self._session("MONDAY", 17, 0, 18, 0)])],
                "PHY": [self._group("GPHY", "PHY", "PANAMÁ", [self._session("TUESDAY", 17, 0, 18, 0)])],
            }
        )
        service = SchedulerService(repository)

        result = service.find_best_schedule(
            ScheduleRequest(
                desired_subjects=["MAT", "PHY", "MAT"],
                required_subjects=[],
                available_start=time(17, 0),
                available_end=time(23, 0),
                desired_province="PANAMÁ",
            )
        )

        self.assertIsNotNone(result)
        self.assertEqual(repository.calls, ["MAT", "PHY"])
        self.assertEqual(
            [enrollment.subject_id for enrollment in result.chosen_enrollments],
            ["MAT", "PHY"],
        )

    def test_required_subjects_must_be_present(self) -> None:
        repository = FakeCatalogRepository(
            {
                "MAT": [self._group("GMAT", "MAT", "PANAMÁ", [self._session("MONDAY", 17, 0, 18, 0)])],
                "CHEM": [self._group("GCHEM", "CHEM", "PANAMÁ", [self._session("TUESDAY", 17, 0, 18, 0)])],
            }
        )
        service = SchedulerService(repository)

        result = service.find_best_schedule(
            ScheduleRequest(
                desired_subjects=["MAT", "PHY", "CHEM"],
                required_subjects=["PHY"],
                available_start=time(17, 0),
                available_end=time(23, 0),
                desired_province="PANAMÁ",
            )
        )

        self.assertIsNone(result)

    def test_allows_out_of_province_groups_only_when_fully_virtual(self) -> None:
        repository = FakeCatalogRepository(
            {
                "MAT": [self._group("GMAT", "MAT", "CHIRIQUÍ", [self._session("MONDAY", 17, 0, 18, 0, classroom="VVIRT")])],
                "PHY": [self._group("GPHY", "PHY", "PANAMÁ", [self._session("TUESDAY", 17, 0, 18, 0)])],
                "CHEM": [self._group("GCHEM", "CHEM", "VERAGUAS", [self._session("WEDNESDAY", 17, 0, 18, 0, classroom="AULA 2")])],
            }
        )
        service = SchedulerService(repository)

        result = service.find_best_schedule(
            ScheduleRequest(
                desired_subjects=["MAT", "PHY", "CHEM"],
                required_subjects=[],
                available_start=time(17, 0),
                available_end=time(23, 0),
                desired_province="PANAMÁ",
            )
        )

        self.assertIsNotNone(result)
        self.assertEqual(
            {enrollment.subject_id for enrollment in result.chosen_enrollments},
            {"MAT", "PHY"},
        )

    def test_expands_lab_groups_into_candidate_enrollments(self) -> None:
        repository = FakeCatalogRepository(
            {
                "MAT": [self._group("GMAT", "MAT", "PANAMÁ", [self._session("MONDAY", 17, 0, 18, 0)])],
                "CHEM": [
                    self._group(
                        "GCHEM",
                        "CHEM",
                        "PANAMÁ",
                        [
                            self._session("TUESDAY", 17, 0, 18, 0, session_type="Theory"),
                            self._session(
                                "WEDNESDAY",
                                17,
                                0,
                                18,
                                0,
                                session_type="Laboratory",
                                lab_code="A",
                            ),
                            self._session(
                                "THURSDAY",
                                17,
                                0,
                                18,
                                0,
                                session_type="Laboratory",
                                lab_code="B",
                            ),
                        ],
                    )
                ],
            }
        )
        service = SchedulerService(repository)

        result = service.find_best_schedule(
            ScheduleRequest(
                desired_subjects=["MAT", "CHEM"],
                required_subjects=[],
                available_start=time(17, 0),
                available_end=time(23, 0),
                desired_province="PANAMÁ",
            )
        )

        self.assertIsNotNone(result)
        self.assertEqual(len(result.chosen_enrollments), 2)
        chem_enrollment = next(
            enrollment for enrollment in result.chosen_enrollments if enrollment.subject_id == "CHEM"
        )
        self.assertEqual(
            {session.lab_code for session in chem_enrollment.sessions if session.lab_code},
            {"A"},
        )
        self.assertEqual(
            len([session for session in chem_enrollment.sessions if session.session_type == "Theory"]),
            1,
        )

    def test_requires_at_least_two_enrollments_to_record_best_solution(self) -> None:
        repository = FakeCatalogRepository(
            {
                "MAT": [self._group("GMAT", "MAT", "PANAMÁ", [self._session("MONDAY", 17, 0, 18, 0)])],
            }
        )
        service = SchedulerService(repository)

        result = service.find_best_schedule(
            ScheduleRequest(
                desired_subjects=["MAT"],
                required_subjects=[],
                available_start=time(17, 0),
                available_end=time(23, 0),
                desired_province="PANAMÁ",
            )
        )

        self.assertIsNone(result)

    def test_prefers_lower_idle_time_when_subject_count_ties(self) -> None:
        repository = FakeCatalogRepository(
            {
                "MAT": [self._group("GMAT", "MAT", "PANAMÁ", [self._session("MONDAY", 17, 0, 18, 0)])],
                "PHY": [
                    self._group("GPHY1", "PHY", "PANAMÁ", [self._session("MONDAY", 18, 0, 19, 0)]),
                    self._group("GPHY2", "PHY", "PANAMÁ", [self._session("TUESDAY", 17, 0, 18, 0)]),
                ],
            }
        )
        service = SchedulerService(repository)

        result = service.find_best_schedule(
            ScheduleRequest(
                desired_subjects=["MAT", "PHY"],
                required_subjects=[],
                available_start=time(17, 0),
                available_end=time(23, 0),
                desired_province="PANAMÁ",
            )
        )

        self.assertIsNotNone(result)
        chosen_phy = next(
            enrollment.group_code for enrollment in result.chosen_enrollments if enrollment.subject_id == "PHY"
        )
        self.assertEqual(chosen_phy, "GPHY1")
        self.assertEqual(result.total_idle_minutes, 240)

    def test_optimized_candidate_order_does_not_change_output_subject_order(self) -> None:
        repository = FakeCatalogRepository(
            {
                "MAT": [
                    self._group("GMAT1", "MAT", "PANAMÁ", [self._session("MONDAY", 17, 0, 18, 0)]),
                    self._group("GMAT2", "MAT", "PANAMÁ", [self._session("MONDAY", 18, 0, 19, 0)]),
                ],
                "PHY": [
                    self._group("GPHY", "PHY", "PANAMÁ", [self._session("TUESDAY", 17, 0, 18, 0)])
                ],
                "CHEM": [
                    self._group("GCHEM", "CHEM", "PANAMÁ", [self._session("WEDNESDAY", 17, 0, 18, 0)])
                ],
            }
        )
        service = SchedulerService(repository)

        result = service.find_best_schedule(
            ScheduleRequest(
                desired_subjects=["MAT", "PHY", "CHEM"],
                required_subjects=[],
                available_start=time(17, 0),
                available_end=time(23, 0),
                desired_province="PANAMÁ",
            )
        )

        self.assertIsNotNone(result)
        self.assertEqual(
            [enrollment.subject_id for enrollment in result.chosen_enrollments],
            ["MAT", "PHY", "CHEM"],
        )

    @staticmethod
    def _group(
        group_code: str,
        subject_id: str,
        province: str,
        sessions: list[SessionRecord],
    ) -> CourseGroup:
        return CourseGroup(
            group_code=group_code,
            subject_id=subject_id,
            province=province,
            sessions=sessions,
        )

    @staticmethod
    def _session(
        day: str,
        start_hour: int,
        start_minute: int,
        end_hour: int,
        end_minute: int,
        *,
        session_type: str = "Theory",
        classroom: str = "AULA 1",
        lab_code: str | None = None,
        subject: str = "SUBJECT",
    ) -> SessionRecord:
        return SessionRecord(
            day=day,
            subject=subject,
            session_type=session_type,
            classroom=classroom,
            lab_code=lab_code,
            start_time=time(start_hour, start_minute),
            end_time=time(end_hour, end_minute),
        )


if __name__ == "__main__":
    unittest.main()
