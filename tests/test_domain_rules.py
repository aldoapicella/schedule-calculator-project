from __future__ import annotations

import unittest
from datetime import time

from schedule_calculator.domain.models import CourseGroup, SessionRecord
from schedule_calculator.domain.rules import (
    ensure_allowed_province,
    extract_lab_code,
    get_conflict_details,
    is_virtual_class,
    normalize_subject,
    parse_time_slot,
    schedule_within_available,
    sessions_conflict,
    split_group_enrollments,
    theory_lab_consistency,
    total_idle_time,
    unique_preserve_order,
)


class DomainRulesTests(unittest.TestCase):
    def test_normalize_subject_and_extract_lab_code(self) -> None:
        self.assertEqual(normalize_subject("FISICA II(A )"), "FISICA II")
        self.assertEqual(normalize_subject("FISICA I (MEC.)"), "FISICA I (MEC.)")
        self.assertEqual(extract_lab_code("FISICA II(A )"), "A")
        self.assertIsNone(extract_lab_code("FISICA I (MEC.)"))

    def test_parse_time_slot_supports_shared_period_suffix(self) -> None:
        start_time, end_time = parse_time_slot("7:50-8:35A.M.")
        self.assertEqual(start_time, time(7, 50))
        self.assertEqual(end_time, time(8, 35))

    def test_parse_time_slot_rejects_invalid_value(self) -> None:
        with self.assertRaises(ValueError):
            parse_time_slot("17:00-18:00")

    def test_is_virtual_class_detects_vvirt_and_dis_rooms(self) -> None:
        self.assertTrue(is_virtual_class("VVIRT"))
        self.assertTrue(is_virtual_class("DIS-101"))
        self.assertFalse(is_virtual_class("AULA 2"))

    def test_sessions_conflict_and_details(self) -> None:
        sessions = [
            self._timed_session("MONDAY", 17, 0, 18, 0),
            self._timed_session("MONDAY", 17, 30, 18, 30),
        ]
        self.assertTrue(sessions_conflict(sessions))
        self.assertEqual(
            get_conflict_details(sessions),
            ["On MONDAY: 17:00-18:00 overlaps with 17:30-18:30"],
        )

    def test_schedule_within_available_and_total_idle_time(self) -> None:
        sessions = [
            self._timed_session("MONDAY", 17, 0, 18, 0),
            self._timed_session("MONDAY", 19, 0, 20, 0),
        ]
        self.assertTrue(schedule_within_available(sessions, time(17, 0), time(23, 0)))
        self.assertFalse(schedule_within_available(sessions, time(18, 0), time(23, 0)))
        self.assertEqual(total_idle_time(sessions, time(17, 0), time(23, 0)), 240)

    def test_theory_lab_consistency_and_lab_split(self) -> None:
        group = CourseGroup(
            group_code="G1",
            subject_id="CHEM",
            province="PANAMÁ",
            sessions=[
                self._timed_session("MONDAY", 17, 0, 18, 0, session_type="Theory"),
                self._timed_session(
                    "WEDNESDAY",
                    17,
                    0,
                    18,
                    0,
                    session_type="Laboratory",
                    lab_code="A",
                ),
                self._timed_session(
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

        self.assertTrue(theory_lab_consistency(group))
        enrollments = split_group_enrollments(group)
        self.assertEqual(len(enrollments), 2)
        self.assertEqual(
            [{session.lab_code for session in enrollment.sessions if session.lab_code} for enrollment in enrollments],
            [{"A"}, {"B"}],
        )

    def test_theory_lab_consistency_fails_without_theory(self) -> None:
        group = CourseGroup(
            group_code="G2",
            subject_id="CHEM",
            province="PANAMÁ",
            sessions=[
                self._timed_session(
                    "MONDAY",
                    17,
                    0,
                    18,
                    0,
                    session_type="Laboratory",
                    lab_code="A",
                )
            ],
        )

        self.assertFalse(theory_lab_consistency(group))
        self.assertEqual(split_group_enrollments(group), [])

    def test_ensure_allowed_province_accepts_accents_and_rejects_unknown(self) -> None:
        ensure_allowed_province("PANAMÁ")
        ensure_allowed_province("PANAMA")
        with self.assertRaises(ValueError):
            ensure_allowed_province("MARS")

    def test_unique_preserve_order_keeps_first_occurrence(self) -> None:
        self.assertEqual(unique_preserve_order(["0698", "0709", "0698", "0760"]), ["0698", "0709", "0760"])

    @staticmethod
    def _timed_session(
        day: str,
        start_hour: int,
        start_minute: int,
        end_hour: int,
        end_minute: int,
        *,
        session_type: str = "Theory",
        lab_code: str | None = None,
        classroom: str = "AULA 1",
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
