from __future__ import annotations

import importlib.util
import io
import tempfile
import unittest
from contextlib import nullcontext, redirect_stderr, redirect_stdout
from datetime import time
from pathlib import Path
from unittest import mock

from schedule_calculator.calendar_view import build_schedule_calendar_view
from schedule_calculator.domain.models import CandidateEnrollment, ScheduleRequest, ScheduleResult, SessionRecord
from schedule_calculator.errors import ConfigurationError
from schedule_calculator.pdf_renderer import render_schedule_calendar_pdf

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CALCULATOR_PATH = PROJECT_ROOT / "data_extractor" / "calculator.py"


class CalendarViewTests(unittest.TestCase):
    def test_build_schedule_calendar_view_uses_mon_to_sat_and_adds_sunday_only_when_needed(self) -> None:
        weekday_view = build_schedule_calendar_view(
            self._request(),
            self._result(
                self._enrollment(
                    "MAT",
                    "GMAT",
                    [
                        self._session("MONDAY", 9, 30, 10, 15),
                        self._session("FRIDAY", 11, 0, 11, 45),
                    ],
                )
            ),
        )
        sunday_view = build_schedule_calendar_view(
            self._request(),
            self._result(
                self._enrollment(
                    "MAT",
                    "GMAT",
                    [
                        self._session("SUNDAY", 9, 30, 10, 15),
                    ],
                )
            ),
        )

        self.assertEqual(
            [day.label for day in weekday_view.days],
            ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"],
        )
        self.assertEqual(
            [day.label for day in sunday_view.days],
            ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
        )

    def test_build_schedule_calendar_view_snaps_visible_range_to_half_hour_boundaries(self) -> None:
        view = build_schedule_calendar_view(
            self._request(),
            self._result(
                self._enrollment(
                    "MAT",
                    "GMAT",
                    [
                        self._session("MONDAY", 7, 50, 8, 35),
                        self._session("TUESDAY", 9, 10, 9, 55),
                    ],
                )
            ),
        )

        self.assertEqual(view.visible_start_minutes, 450)
        self.assertEqual(view.visible_end_minutes, 600)
        self.assertEqual(view.time_markers, [450, 480, 510, 540, 570, 600])

    def test_build_schedule_calendar_view_uses_stable_legend_order_and_subject_colors(self) -> None:
        result = self._result(
            self._enrollment(
                "PHY",
                "GPHY",
                [self._session("TUESDAY", 18, 0, 18, 45)],
                subject_name="Physics",
                hour_code="801",
            ),
            self._enrollment(
                "MAT",
                "GMAT",
                [self._session("MONDAY", 17, 0, 17, 45)],
                subject_name="Mathematics",
                hour_code="800",
            ),
        )

        view = build_schedule_calendar_view(self._request(), result)

        self.assertEqual(
            [legend.subject_id for legend in view.legend],
            ["PHY", "MAT"],
        )
        phy_colors = {block.color_hex for block in view.blocks if block.subject_id == "PHY"}
        mat_colors = {block.color_hex for block in view.blocks if block.subject_id == "MAT"}
        self.assertEqual(len(phy_colors), 1)
        self.assertEqual(len(mat_colors), 1)
        self.assertNotEqual(phy_colors, mat_colors)
        self.assertEqual(view.legend[0].label, "PHY Physics:GPHY (CODHORA: 801)")
        self.assertEqual(view.legend[1].label, "MAT Mathematics:GMAT (CODHORA: 800)")

    def test_build_schedule_calendar_view_block_labels_include_session_details(self) -> None:
        view = build_schedule_calendar_view(
            self._request(),
            self._result(
                self._enrollment(
                    "CHEM",
                    "GCHEM",
                    [
                        self._session(
                            "WEDNESDAY",
                            9,
                            0,
                            10,
                            30,
                            session_type="Laboratory",
                            classroom="VVIRT",
                            lab_code="L",
                        )
                    ],
                    subject_name="Chemistry",
                    hour_code="902",
                )
            ),
        )

        block = view.blocks[0]
        self.assertEqual(
            block.label_lines,
            (
                "CHEM Chemistry",
                "Group: GCHEM | CODHORA: 902",
                "Laboratory (L)",
                "09:00-10:30",
                "Classroom: VVIRT",
            ),
        )

    @staticmethod
    def _request() -> ScheduleRequest:
        return ScheduleRequest(
            desired_subjects=["MAT", "PHY", "CHEM"],
            required_subjects=[],
            available_start=time(7, 0),
            available_end=time(23, 0),
            desired_province="PANAMÁ",
        )

    @staticmethod
    def _result(*enrollments: CandidateEnrollment) -> ScheduleResult:
        return ScheduleResult(
            chosen_enrollments=list(enrollments),
            final_schedule=[session for enrollment in enrollments for session in enrollment.sessions],
            total_idle_minutes=180,
        )

    @staticmethod
    def _enrollment(
        subject_id: str,
        group_code: str,
        sessions: list[SessionRecord],
        *,
        subject_name: str = "",
        hour_code: str = "",
    ) -> CandidateEnrollment:
        return CandidateEnrollment(
            group_code=group_code,
            subject_id=subject_id,
            province="PANAMÁ",
            sessions=sessions,
            subject_name=subject_name,
            hour_code=hour_code,
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
        classroom: str = "3-409",
        lab_code: str | None = None,
    ) -> SessionRecord:
        return SessionRecord(
            day=day,
            subject="",
            session_type=session_type,
            classroom=classroom,
            lab_code=lab_code,
            start_time=time(start_hour, start_minute),
            end_time=time(end_hour, end_minute),
        )


class PdfRendererTests(unittest.TestCase):
    @unittest.skipUnless(
        importlib.util.find_spec("reportlab") is not None,
        "reportlab is not installed",
    )
    def test_render_schedule_calendar_pdf_writes_pdf_file(self) -> None:
        view = build_schedule_calendar_view(
            CalendarViewTests._request(),
            CalendarViewTests._result(
                CalendarViewTests._enrollment(
                    "MAT",
                    "GMAT",
                    [
                        CalendarViewTests._session("MONDAY", 17, 0, 17, 45),
                        CalendarViewTests._session("WEDNESDAY", 18, 0, 18, 45),
                    ],
                ),
                CalendarViewTests._enrollment(
                    "PHY",
                    "GPHY",
                    [CalendarViewTests._session("TUESDAY", 19, 0, 19, 45)],
                ),
            ),
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "nested" / "schedule.pdf"
            render_schedule_calendar_pdf(view, output_path)

            payload = output_path.read_bytes()
            self.assertTrue(output_path.exists())
            self.assertGreater(len(payload), 32)
            self.assertTrue(payload.startswith(b"%PDF"))


class CalculatorPdfCliTests(unittest.TestCase):
    def test_calculator_main_writes_pdf_when_requested_and_schedule_exists(self) -> None:
        module = self._load_calculator_module()
        result = CalendarViewTests._result(
            CalendarViewTests._enrollment(
                "MAT",
                "GMAT",
                [CalendarViewTests._session("MONDAY", 17, 0, 17, 45)],
            ),
            CalendarViewTests._enrollment(
                "PHY",
                "GPHY",
                [CalendarViewTests._session("TUESDAY", 18, 0, 18, 45)],
            ),
        )
        stdout = io.StringIO()
        stderr = io.StringIO()

        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "exports" / "schedule.pdf"

            def write_fake_pdf(_, pdf_output: str | Path) -> Path:
                path = Path(pdf_output)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"%PDF-FAKE")
                return path

            with mock.patch.object(module, "configure_logging"), mock.patch.object(
                module, "load_database_config", return_value=object()
            ), mock.patch.object(
                module, "postgres_connection", return_value=nullcontext(object())
            ), mock.patch.object(
                module, "PostgresGroupCatalogRepository", return_value=object()
            ), mock.patch.object(
                module, "SchedulerService"
            ) as scheduler_service_cls, mock.patch.object(
                module, "build_schedule_calendar_view", return_value=object()
            ), mock.patch.object(
                module, "render_schedule_calendar_pdf", side_effect=write_fake_pdf
            ), mock.patch.object(
                module, "log_exception_summary"
            ), redirect_stdout(stdout), redirect_stderr(stderr):
                scheduler_service_cls.return_value.find_best_schedule.return_value = result
                exit_code = module.main(
                    [
                        "--subjects",
                        "MAT,PHY",
                        "--available-start",
                        "17:00",
                        "--available-end",
                        "23:00",
                        "--province",
                        "PANAMÁ",
                        "--pdf-output",
                        str(output_path),
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr.getvalue(), "")
            self.assertTrue(output_path.exists())
            self.assertIn("Schedule found!", stdout.getvalue())
            self.assertIn(f"PDF saved to {output_path}", stdout.getvalue())

    def test_calculator_main_does_not_write_pdf_when_no_schedule_exists(self) -> None:
        module = self._load_calculator_module()
        stdout = io.StringIO()
        stderr = io.StringIO()

        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "schedule.pdf"
            with mock.patch.object(module, "configure_logging"), mock.patch.object(
                module, "load_database_config", return_value=object()
            ), mock.patch.object(
                module, "postgres_connection", return_value=nullcontext(object())
            ), mock.patch.object(
                module, "PostgresGroupCatalogRepository", return_value=object()
            ), mock.patch.object(
                module, "SchedulerService"
            ) as scheduler_service_cls, mock.patch.object(
                module, "build_schedule_calendar_view"
            ) as build_view, mock.patch.object(
                module, "render_schedule_calendar_pdf"
            ) as render_pdf, mock.patch.object(
                module, "log_exception_summary"
            ), redirect_stdout(stdout), redirect_stderr(stderr):
                scheduler_service_cls.return_value.find_best_schedule.return_value = None
                exit_code = module.main(
                    [
                        "--subjects",
                        "MAT,PHY",
                        "--available-start",
                        "17:00",
                        "--available-end",
                        "23:00",
                        "--province",
                        "PANAMÁ",
                        "--pdf-output",
                        str(output_path),
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr.getvalue(), "")
            self.assertEqual(stdout.getvalue().strip(), "No valid schedule found.")
            self.assertFalse(output_path.exists())
            build_view.assert_not_called()
            render_pdf.assert_not_called()

    def test_calculator_main_returns_config_error_when_pdf_dependency_is_missing(self) -> None:
        module = self._load_calculator_module()
        result = CalendarViewTests._result(
            CalendarViewTests._enrollment(
                "MAT",
                "GMAT",
                [CalendarViewTests._session("MONDAY", 17, 0, 17, 45)],
            ),
            CalendarViewTests._enrollment(
                "PHY",
                "GPHY",
                [CalendarViewTests._session("TUESDAY", 18, 0, 18, 45)],
            ),
        )
        stdout = io.StringIO()
        stderr = io.StringIO()

        with mock.patch.object(module, "configure_logging"), mock.patch.object(
            module, "load_database_config", return_value=object()
        ), mock.patch.object(
            module, "postgres_connection", return_value=nullcontext(object())
        ), mock.patch.object(
            module, "PostgresGroupCatalogRepository", return_value=object()
        ), mock.patch.object(
            module, "SchedulerService"
        ) as scheduler_service_cls, mock.patch.object(
            module, "build_schedule_calendar_view", return_value=object()
        ), mock.patch.object(
            module,
            "render_schedule_calendar_pdf",
            side_effect=ConfigurationError(
                "reportlab is not installed. Install it to use PDF schedule export."
            ),
        ), mock.patch.object(
            module, "log_exception_summary"
        ), redirect_stdout(stdout), redirect_stderr(stderr):
            scheduler_service_cls.return_value.find_best_schedule.return_value = result
            exit_code = module.main(
                [
                    "--subjects",
                    "MAT,PHY",
                    "--available-start",
                    "17:00",
                    "--available-end",
                    "23:00",
                    "--province",
                    "PANAMÁ",
                    "--pdf-output",
                    "artifacts/schedule.pdf",
                ]
            )

        self.assertEqual(exit_code, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("reportlab is not installed", stderr.getvalue())

    @staticmethod
    def _load_calculator_module():
        spec = importlib.util.spec_from_file_location("calculator_script_for_tests", CALCULATOR_PATH)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module


if __name__ == "__main__":
    unittest.main()
