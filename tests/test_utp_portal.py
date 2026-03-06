from __future__ import annotations

import time
import unittest
from pathlib import Path
from unittest import mock

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
            [(row.event_target, row.group_code, row.hour_code) for row in rows],
            [
                ("ctl00$cphContenido$gvlistado$ctl02$lnkHorario", "1IL131", "100"),
                ("ctl00$cphContenido$gvlistado$ctl03$lnkHorario", "1IL132", "200"),
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

    def test_fetch_groups_for_subject_preserves_listing_order_with_parallel_detail_fetches(self) -> None:
        session = FakeSession(
            get_responses=[
                FakeResponse(
                    self._selection_page_html(),
                    url="https://matricula.utp.ac.pa/clistagrupo/menu/procesos/2026/token",
                )
            ],
            post_responses=[
                FakeResponse(
                    self._group_rows_page_html(
                        [
                            "ctl00$cphContenido$gvlistado$ctl02$lnkHorario",
                            "ctl00$cphContenido$gvlistado$ctl03$lnkHorario",
                        ]
                    ),
                    url="https://matricula.utp.ac.pa/clistagrupo/menu/procesos/2026/token",
                )
            ],
        )
        worker_sessions = [
            WorkerSession(
                post_responses=[FakeResponse(self._detail_html("GROUPA"))],
                delay_seconds=0.15,
            ),
            WorkerSession(
                post_responses=[FakeResponse(self._detail_html("GROUPB"))],
            ),
        ]
        client = UTPPortalClient(
            base_url="https://matricula.utp.ac.pa/",
            session=session,
            group_concurrency=2,
        )
        client.menu_url = "https://matricula.utp.ac.pa/mprematr/menu/inicio/2026/token"
        client.group_list_url = "https://matricula.utp.ac.pa/clistagrupo/menu/procesos/2026/token"

        with mock.patch(
            "schedule_calculator.infrastructure.utp_portal.requests.Session",
            side_effect=worker_sessions,
        ):
            groups = client.fetch_groups_for_subject("0698")

        self.assertEqual(
            [group.header.group_code for group in groups],
            ["GROUPA", "GROUPB"],
        )
        self.assertEqual([group.header.hour_code for group in groups], ["100", "200"])

    def test_parallel_detail_fetch_bubbles_failure_without_returning_partial_results(self) -> None:
        session = FakeSession(
            get_responses=[
                FakeResponse(
                    self._selection_page_html(),
                    url="https://matricula.utp.ac.pa/clistagrupo/menu/procesos/2026/token",
                )
            ],
            post_responses=[
                FakeResponse(
                    self._group_rows_page_html(
                        [
                            "ctl00$cphContenido$gvlistado$ctl02$lnkHorario",
                            "ctl00$cphContenido$gvlistado$ctl03$lnkHorario",
                        ]
                    ),
                    url="https://matricula.utp.ac.pa/clistagrupo/menu/procesos/2026/token",
                )
            ],
        )
        worker_sessions = [
            WorkerSession(
                post_responses=[
                    FakeResponse("", raise_for_status_error=requests.HTTPError("boom"))
                ]
            ),
            WorkerSession(
                post_responses=[FakeResponse(self._detail_html("GROUPB"))],
                delay_seconds=0.1,
            ),
        ]
        client = UTPPortalClient(
            base_url="https://matricula.utp.ac.pa/",
            session=session,
            group_concurrency=2,
            max_attempts=1,
        )
        client.menu_url = "https://matricula.utp.ac.pa/mprematr/menu/inicio/2026/token"
        client.group_list_url = "https://matricula.utp.ac.pa/clistagrupo/menu/procesos/2026/token"

        with mock.patch(
            "schedule_calculator.infrastructure.utp_portal.requests.Session",
            side_effect=worker_sessions,
        ):
            with self.assertRaises(PortalRequestError):
                client.fetch_groups_for_subject("0698")

    def test_worker_sessions_inherit_authenticated_headers_and_cookies(self) -> None:
        session = FakeSession(
            get_responses=[
                FakeResponse(
                    self._selection_page_html(),
                    url="https://matricula.utp.ac.pa/clistagrupo/menu/procesos/2026/token",
                )
            ],
            post_responses=[
                FakeResponse(
                    self._group_rows_page_html(
                        ["ctl00$cphContenido$gvlistado$ctl02$lnkHorario"]
                    ),
                    url="https://matricula.utp.ac.pa/clistagrupo/menu/procesos/2026/token",
                )
            ],
            cookies={"ASP.NET_SessionId": "session-cookie"},
            default_headers={"X-Test": "present"},
        )
        worker_session = WorkerSession(
            post_responses=[FakeResponse(self._detail_html("GROUPA"))]
        )
        client = UTPPortalClient(
            base_url="https://matricula.utp.ac.pa/",
            session=session,
            group_concurrency=1,
        )
        client.menu_url = "https://matricula.utp.ac.pa/mprematr/menu/inicio/2026/token"
        client.group_list_url = "https://matricula.utp.ac.pa/clistagrupo/menu/procesos/2026/token"

        with mock.patch(
            "schedule_calculator.infrastructure.utp_portal.requests.Session",
            return_value=worker_session,
        ):
            client.fetch_groups_for_subject("0698")

        self.assertEqual(worker_session.headers.get("X-Test"), "present")
        self.assertEqual(worker_session.cookies.get("ASP.NET_SessionId"), "session-cookie")

    def _selection_page_html(self) -> str:
        return """
        <html>
          <body>
            <form id="frmMaster" action="./selection-token">
              <input type="hidden" name="__VIEWSTATE" value="selection-viewstate" />
              <input type="hidden" name="__EVENTVALIDATION" value="selection-eventvalidation" />
              <input type="hidden" name="__VIEWSTATEGENERATOR" value="selection-generator" />
            </form>
          </body>
        </html>
        """

    def _group_rows_page_html(self, event_targets: list[str]) -> str:
        rows = []
        for index, event_target in enumerate(event_targets, start=1):
            group_code = f"GROUP{chr(64 + index)}"
            hour_code = f"{index}00"
            columns = "".join(
                [
                    "<td>PANAMÁ</td>",
                    "<td>Ingeniería</td>",
                    f"<td>{group_code}</td>",
                    f"<td>{hour_code}</td>",
                    "<td>A</td>",
                    "<td>No</td>",
                    "<td>Si</td>",
                    "<td>No</td>",
                    "<td>No</td>",
                ]
            )
            columns += (
                f"<td><a href=\"javascript:__doPostBack('{event_target}','')\">Horario</a></td>"
            )
            rows.append(f"<tr>{columns}</tr>")
        return (
            """
            <html>
              <body>
                <form id="frmMaster" action="./groups-token">
                  <input type="hidden" name="__VIEWSTATE" value="groups-viewstate" />
                  <input type="hidden" name="__EVENTVALIDATION" value="groups-eventvalidation" />
                  <input type="hidden" name="__VIEWSTATEGENERATOR" value="groups-generator" />
                </form>
                <table id="cphContenido_gvlistado">
                  <tr>
                    <th>1</th><th>2</th><th>3</th><th>4</th><th>5</th>
                    <th>6</th><th>7</th><th>8</th><th>9</th><th>10</th>
                  </tr>
            """
            + "".join(rows)
            + """
                </table>
              </body>
            </html>
            """
        )

    def _detail_html(self, group_code: str) -> str:
        return read_fixture("portal_group_detail.html").replace(
            "PANAMÁ - 1IL131",
            f"PANAMÁ - {group_code}",
        )


class FakeResponse:
    def __init__(
        self,
        text: str,
        raise_for_status_error: Exception | None = None,
        url: str = "https://matricula.utp.ac.pa/",
    ) -> None:
        self.text = text
        self._raise_for_status_error = raise_for_status_error
        self.url = url

    def raise_for_status(self) -> None:
        if self._raise_for_status_error is not None:
            raise self._raise_for_status_error


class FakeSession:
    def __init__(
        self,
        *,
        get_responses: list[FakeResponse] | None = None,
        post_responses: list[FakeResponse] | None = None,
        cookies: dict[str, str] | None = None,
        default_headers: dict[str, str] | None = None,
    ) -> None:
        self.get_responses = get_responses or []
        self.post_responses = post_responses or []
        self.headers: dict[str, str] = {}
        self.cookies = requests.cookies.RequestsCookieJar()
        for key, value in (cookies or {}).items():
            self.cookies.set(key, value)
        self.auth = None
        self.proxies: dict[str, str] = {}
        self.verify = True
        self.cert = None
        self.stream = False
        self.trust_env = True
        self.max_redirects = 30
        self.hooks: dict[str, list] = {}
        self.get_calls: list[tuple[str, int | None, dict[str, str] | None]] = []
        self.post_calls: list[tuple[str, dict[str, str], int | None, dict[str, str] | None]] = []
        if default_headers:
            self.headers.update(default_headers)

    def get(
        self,
        url: str,
        timeout: int | None = None,
        headers: dict[str, str] | None = None,
    ) -> FakeResponse:
        self.get_calls.append((url, timeout, headers))
        if not self.get_responses:
            raise AssertionError("Unexpected GET call")
        return self.get_responses.pop(0)

    def post(
        self,
        url: str,
        data: dict[str, str],
        timeout: int | None = None,
        headers: dict[str, str] | None = None,
    ) -> FakeResponse:
        self.post_calls.append((url, data, timeout, headers))
        if not self.post_responses:
            raise AssertionError("Unexpected POST call")
        return self.post_responses.pop(0)

    def close(self) -> None:
        return None


class WorkerSession(FakeSession):
    def __init__(
        self,
        *,
        get_responses: list[FakeResponse] | None = None,
        post_responses: list[FakeResponse] | None = None,
        delay_seconds: float = 0.0,
    ) -> None:
        super().__init__(get_responses=get_responses, post_responses=post_responses)
        self.delay_seconds = delay_seconds

    def post(
        self,
        url: str,
        data: dict[str, str],
        timeout: int | None = None,
        headers: dict[str, str] | None = None,
    ) -> FakeResponse:
        if self.delay_seconds > 0:
            time.sleep(self.delay_seconds)
        return super().post(url, data, timeout=timeout, headers=headers)


if __name__ == "__main__":
    unittest.main()
