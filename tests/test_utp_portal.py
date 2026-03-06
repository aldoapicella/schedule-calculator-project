from __future__ import annotations

import unittest
from pathlib import Path

import requests

from schedule_calculator.domain.models import PortalCredentials
from schedule_calculator.errors import PortalParseError, PortalRequestError
from schedule_calculator.infrastructure.utp_portal import (
    UTPPortalClient,
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

    def test_parse_portal_state_rejects_missing_form(self) -> None:
        with self.assertRaises(PortalParseError):
            parse_portal_state("<html><body></body></html>", "ctl01")

    def test_extract_group_list_url_rejects_missing_link(self) -> None:
        with self.assertRaises(PortalParseError):
            extract_group_list_url("<html><body></body></html>", "https://matricula.utp.ac.pa/")

    def test_portal_client_requires_authentication_before_fetch(self) -> None:
        client = UTPPortalClient(base_url="https://matricula.utp.ac.pa/")
        with self.assertRaises(PortalRequestError):
            client.fetch_groups_for_subject("0698")

    def test_portal_client_rejects_unknown_profile_label(self) -> None:
        session = FakeSession(
            get_responses=[FakeResponse(read_fixture("portal_login.html"))],
            post_responses=[FakeResponse(read_fixture("portal_profiles.html"))],
        )
        client = UTPPortalClient(base_url="https://matricula.utp.ac.pa/", session=session)

        with self.assertRaises(PortalParseError):
            client.authenticate(
                PortalCredentials(
                    username="20-70-5158",
                    password="secret",
                    profile_label="Unknown",
                )
            )

    def test_portal_client_surfaces_http_error_during_authentication(self) -> None:
        session = FakeSession(
            get_responses=[
                FakeResponse("", raise_for_status_error=requests.HTTPError("boom")),
                FakeResponse("", raise_for_status_error=requests.HTTPError("boom")),
                FakeResponse("", raise_for_status_error=requests.HTTPError("boom")),
            ]
        )
        client = UTPPortalClient(base_url="https://matricula.utp.ac.pa/", session=session)

        with self.assertRaises(PortalRequestError):
            client.authenticate(
                PortalCredentials(
                    username="20-70-5158",
                    password="secret",
                    profile_label="Estudiantes",
                )
            )

    def test_portal_request_error_redacts_query_string_details(self) -> None:
        session = FakeSession(
            get_responses=[
                FakeResponse("", raise_for_status_error=requests.HTTPError("boom")),
                FakeResponse("", raise_for_status_error=requests.HTTPError("boom")),
                FakeResponse("", raise_for_status_error=requests.HTTPError("boom")),
            ]
        )
        client = UTPPortalClient(base_url="https://matricula.utp.ac.pa/", session=session)
        client.group_list_url = "https://matricula.utp.ac.pa/estudiante/grupos/listado?ticket=secret"

        with self.assertRaises(PortalRequestError) as context:
            client.fetch_groups_for_subject("0698")

        self.assertIn(
            "GET https://matricula.utp.ac.pa/estudiante/grupos/listado",
            str(context.exception),
        )
        self.assertNotIn("ticket=secret", str(context.exception))


class FakeResponse:
    def __init__(self, text: str, raise_for_status_error: Exception | None = None) -> None:
        self.text = text
        self._raise_for_status_error = raise_for_status_error

    def raise_for_status(self) -> None:
        if self._raise_for_status_error is not None:
            raise self._raise_for_status_error


class FakeSession:
    def __init__(
        self,
        *,
        get_responses: list[FakeResponse] | None = None,
        post_responses: list[FakeResponse] | None = None,
    ) -> None:
        self.get_responses = get_responses or []
        self.post_responses = post_responses or []
        self.headers: dict[str, str] = {}
        self.get_calls: list[tuple[str, int | None]] = []
        self.post_calls: list[tuple[str, dict[str, str], int | None]] = []

    def get(self, url: str, timeout: int | None = None) -> FakeResponse:
        self.get_calls.append((url, timeout))
        if not self.get_responses:
            raise AssertionError("Unexpected GET call")
        return self.get_responses.pop(0)

    def post(self, url: str, data: dict[str, str], timeout: int | None = None) -> FakeResponse:
        self.post_calls.append((url, data, timeout))
        if not self.post_responses:
            raise AssertionError("Unexpected POST call")
        return self.post_responses.pop(0)


if __name__ == "__main__":
    unittest.main()
