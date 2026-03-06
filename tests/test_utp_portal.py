from __future__ import annotations

import unittest
from pathlib import Path

from schedule_calculator.infrastructure.utp_portal import (
    extract_group_list_url,
    parse_group_detail_html,
    parse_group_rows,
    parse_portal_state,
    parse_profile_options,
)


FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def read_fixture(name: str) -> str:
    return (FIXTURES_DIR / name).read_text(encoding="utf-8")


class PortalParserTests(unittest.TestCase):
    def test_parse_portal_state_extracts_core_tokens_and_extra_fields(self) -> None:
        state = parse_portal_state(read_fixture("portal_login.html"), "ctl01")

        self.assertEqual(state.viewstate, "login-viewstate")
        self.assertEqual(state.eventvalidation, "login-eventvalidation")
        self.assertEqual(state.viewstategenerator, "login-generator")
        self.assertEqual(state.action, "./login-token")
        self.assertEqual(state.eventtarget, "existing-target")
        self.assertEqual(state.eventargument, "existing-argument")
        self.assertEqual(state.lastfocus, "existing-focus")
        self.assertEqual(state.extra_fields["customHiddenField"], "custom-value")

    def test_parse_profile_options_uses_radio_labels(self) -> None:
        options = parse_profile_options(read_fixture("portal_profiles.html"))

        self.assertEqual(
            options,
            {
                "Estudiantes": "ESTUDIANTES_VALUE",
                "Servicios": "SERVICIOS_VALUE",
            },
        )

    def test_extract_group_list_url_normalizes_relative_href_and_strips_aspx(self) -> None:
        url = extract_group_list_url(
            read_fixture("portal_dashboard.html"),
            "https://matricula.utp.ac.pa/",
        )

        self.assertEqual(url, "https://matricula.utp.ac.pa/estudiante/grupos/listado")

    def test_parse_group_rows_extracts_event_targets(self) -> None:
        rows = parse_group_rows(read_fixture("portal_group_rows.html"))

        self.assertEqual(
            [row.event_target for row in rows],
            [
                "ctl00$cphContenido$gvlistado$ctl02$lnkHorario",
                "ctl00$cphContenido$gvlistado$ctl03$lnkHorario",
            ],
        )

    def test_parse_group_detail_html_builds_importer_compatible_group(self) -> None:
        scraped_group = parse_group_detail_html(read_fixture("portal_group_detail.html"))

        self.assertEqual(scraped_group.header.group_code, "1IL131")
        self.assertEqual(scraped_group.header.province, "PANAMÁ")
        self.assertEqual(scraped_group.header.faculty, "Facultad de Ingeniería Civil")
        self.assertEqual(scraped_group.header.period, "I")
        self.assertEqual(scraped_group.header.year, "2025")

        self.assertEqual(len(scraped_group.sessions), 2)
        theory_session, lab_session = scraped_group.sessions
        self.assertEqual(theory_session.day, "MONDAY")
        self.assertEqual(theory_session.subject, "FÍSICA I")
        self.assertEqual(theory_session.session_type, "Theory")
        self.assertEqual(theory_session.classroom, "101")
        self.assertEqual(theory_session.time_slot, "7:50-8:35A.M.")

        self.assertEqual(lab_session.day, "WEDNESDAY")
        self.assertEqual(lab_session.subject, "FÍSICA II(A )")
        self.assertEqual(lab_session.session_type, "Laboratory")
        self.assertEqual(lab_session.lab_code, "A")
        self.assertEqual(lab_session.classroom, "DIS-01")

        self.assertEqual(len(scraped_group.subject_professors), 2)
        self.assertEqual(scraped_group.subject_professors[0].subject_code, "0698")
        self.assertEqual(scraped_group.subject_professors[1].professor_email, "carlos@example.com")

        payload = scraped_group.to_dict()
        self.assertEqual(sorted(payload.keys()), ["header", "sessions", "subject_professors"])
        self.assertEqual(payload["header"]["group_code"], "1IL131")
        self.assertEqual(payload["sessions"][1]["lab_code"], "A")
        self.assertEqual(payload["subject_professors"][0]["professor"]["name"], "Ana Profesor")


if __name__ == "__main__":
    unittest.main()
