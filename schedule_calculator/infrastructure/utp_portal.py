from __future__ import annotations

from concurrent.futures import FIRST_EXCEPTION, ThreadPoolExecutor, wait
from dataclasses import dataclass
import logging
import threading
import time
from urllib.parse import unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from schedule_calculator.domain.models import (
    GroupHeader,
    PortalCredentials,
    PortalSessionState,
    ScrapedGroup,
    SessionRecord,
    SubjectProfessor,
)
from schedule_calculator.domain.rules import extract_lab_code
from schedule_calculator.errors import PortalParseError, PortalRequestError

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-419,es;q=0.9,en;q=0.8",
}


@dataclass(slots=True)
class GroupListing:
    event_target: str


@dataclass(slots=True)
class ProfileChoice:
    value: str
    event_target: str


def parse_portal_state(html: str, form_id: str) -> PortalSessionState:
    soup = BeautifulSoup(html, "html.parser")
    form = soup.find("form", {"id": form_id})
    if form is None:
        raise PortalParseError(f"Unable to find form '{form_id}'.")

    inputs = {
        input_tag.get("name", ""): input_tag.get("value", "")
        for input_tag in form.find_all("input")
        if input_tag.get("name")
    }
    return PortalSessionState(
        viewstate=inputs.get("__VIEWSTATE", ""),
        eventvalidation=inputs.get("__EVENTVALIDATION", ""),
        viewstategenerator=inputs.get("__VIEWSTATEGENERATOR", ""),
        action=form.get("action", ""),
        eventtarget=inputs.get("__EVENTTARGET", ""),
        eventargument=inputs.get("__EVENTARGUMENT", ""),
        lastfocus=inputs.get("__LASTFOCUS", ""),
        extra_fields={
            key: value
            for key, value in inputs.items()
            if key
            not in {
                "__VIEWSTATE",
                "__EVENTVALIDATION",
                "__VIEWSTATEGENERATOR",
                "__EVENTTARGET",
                "__EVENTARGUMENT",
                "__LASTFOCUS",
            }
        },
    )


def parse_profile_options(html: str) -> dict[str, str]:
    return {
        label: choice.value
        for label, choice in parse_profile_choices(html).items()
    }


def parse_profile_choices(html: str) -> dict[str, ProfileChoice]:
    soup = BeautifulSoup(html, "html.parser")
    options: dict[str, ProfileChoice] = {}
    for input_tag in soup.find_all("input", {"type": "radio"}):
        name = input_tag.get("name", "")
        if "rblPerfiles" not in name:
            continue
        input_id = input_tag.get("id", "")
        label = soup.find("label", {"for": input_id})
        label_text = label.get_text(strip=True) if label else input_tag.get("value", "").strip()
        index = input_id.rsplit("_", 1)[-1] if "_" in input_id else ""
        event_target = f"{name}${index}" if index.isdigit() else name
        options[label_text] = ProfileChoice(
            value=input_tag.get("value", "").strip(),
            event_target=event_target,
        )
    return options


def extract_group_list_url(html: str, base_url: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    group_list_link = soup.find("a", {"id": "mListag"})
    if group_list_link is None or not group_list_link.get("href"):
        raise PortalParseError("Unable to find group list link.")
    href = group_list_link["href"]
    return urljoin(base_url, href).replace(".aspx", "")


def extract_async_redirect_url(response_text: str, current_url: str) -> str:
    marker = "pageRedirect||"
    marker_index = response_text.find(marker)
    if marker_index < 0:
        raise PortalParseError("Unable to find async redirect in profile response.")
    redirect_fragment = response_text[marker_index + len(marker):].split("|", 1)[0]
    if not redirect_fragment:
        raise PortalParseError("Async redirect response is empty.")
    return urljoin(current_url, unquote(redirect_fragment))


def parse_group_rows(html: str) -> list[GroupListing]:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", {"id": "cphContenido_gvlistado"})
    if table is None:
        return []

    groups: list[GroupListing] = []
    for row in table.find_all("tr")[1:]:
        columns = row.find_all("td")
        if len(columns) < 10:
            continue
        horario_link = columns[9].find("a")
        if horario_link is None:
            continue
        href = horario_link.get("href", "")
        if "javascript:__doPostBack" not in href:
            continue
        parts = href.split("'")
        if len(parts) < 2:
            continue
        groups.append(GroupListing(event_target=parts[1]))
    return groups


def parse_group_detail_html(html: str) -> ScrapedGroup:
    soup = BeautifulSoup(html, "html.parser")
    return ScrapedGroup(
        header=_parse_group_header(soup),
        sessions=_parse_group_sessions(soup),
        subject_professors=_parse_subject_professors(soup),
    )


class UTPPortalClient:
    def __init__(
        self,
        base_url: str,
        session: requests.Session | None = None,
        timeout: int = 30,
        logger: logging.Logger | None = None,
        max_attempts: int = 3,
        backoff_seconds: float = 0.2,
        group_concurrency: int = 6,
    ) -> None:
        if group_concurrency < 1:
            raise ValueError("group_concurrency must be at least 1.")
        self.base_url = base_url.rstrip("/") + "/"
        self.session = session or requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)
        self.timeout = timeout
        self.logger = logger or logging.getLogger(__name__)
        self.max_attempts = max_attempts
        self.backoff_seconds = backoff_seconds
        self.group_concurrency = group_concurrency
        self.group_list_url: str | None = None
        self.menu_url: str | None = None

    def authenticate(self, credentials: PortalCredentials) -> None:
        login_response = self._request("get", self.base_url)
        login_state = parse_portal_state(login_response.text, "ctl01")

        login_url = self._build_action_url(login_response.url, login_state.action)
        login_payload = login_state.as_payload()
        login_payload.update(
            {
                "__EVENTTARGET": "",
                "__EVENTARGUMENT": "",
                "ctl00$MainContent$btnEnviar": "Iniciar Sesión",
                "ctl00$MainContent$txtCedSIU": "",
                "ctl00$MainContent$txtCedUser": credentials.username,
                "ctl00$MainContent$txtPassUser": credentials.password,
                "ctl00$ctl09": "ctl00$MainContent$UpdatePanel2|ctl00$MainContent$btnEnviar",
            }
        )

        profile_response = self._request(
            "post",
            login_url,
            data=login_payload,
        )
        profile_state = parse_portal_state(profile_response.text, "ctl01")
        profile_choices = parse_profile_choices(profile_response.text)

        profile_choice = self._match_profile_choice(profile_choices, credentials.profile_label)
        if profile_choice is None:
            raise PortalParseError(
                f"Profile '{credentials.profile_label}' not found. Available: {sorted(profile_choices)}"
            )

        profile_url = self._build_action_url(profile_response.url, profile_state.action)
        profile_payload = profile_state.as_payload()
        profile_payload.update(
            {
                "__EVENTTARGET": profile_choice.event_target,
                "__EVENTARGUMENT": "",
                "ctl00$MainContent$rblPerfiles": profile_choice.value,
                "ctl00$ctl09": f"{profile_choice.event_target}|{profile_choice.event_target}",
                "__ASYNCPOST": "true",
            }
        )
        profile_redirect_response = self._request(
            "post",
            profile_url,
            data=profile_payload,
            headers={
                "X-MicrosoftAjax": "Delta=true",
                "X-Requested-With": "XMLHttpRequest",
                "Cache-Control": "no-cache",
                "Origin": "https://matricula.utp.ac.pa",
                "Referer": profile_response.url,
            },
        )
        menu_url = extract_async_redirect_url(profile_redirect_response.text, profile_redirect_response.url)
        dashboard_response = self._request(
            "get",
            menu_url,
            headers={"Referer": profile_response.url},
        )
        self.menu_url = dashboard_response.url
        self.group_list_url = extract_group_list_url(dashboard_response.text, dashboard_response.url)

    def fetch_groups_for_subject(self, subject_id: str) -> list[ScrapedGroup]:
        if not self.group_list_url:
            raise PortalRequestError("Portal client is not authenticated.")

        selection_headers = {"Referer": self.menu_url} if self.menu_url else None
        selection_response = self._request("get", self.group_list_url, headers=selection_headers)
        selection_state = parse_portal_state(selection_response.text, "frmMaster")
        selection_url = self._build_action_url(selection_response.url, selection_state.action)

        subject_payload = selection_state.as_payload()
        subject_payload.update(
            {
                "__EVENTTARGET": "ctl00$cphContenido$btnEnviar",
                "__EVENTARGUMENT": "",
                "ctl00$cphContenido$lista": "Rbasigdelplan",
                "ctl00$cphContenido$ddlasignaturas": subject_id,
            }
        )
        groups_response = self._request(
            "post",
            selection_url,
            data=subject_payload,
            headers={"Referer": selection_response.url},
        )
        groups_state = parse_portal_state(groups_response.text, "frmMaster")
        group_listings = parse_group_rows(groups_response.text)
        detail_url = self._build_action_url(groups_response.url, groups_state.action)
        detail_payload_template = groups_state.as_payload()
        return self._fetch_group_details(
            detail_url,
            groups_response.url,
            detail_payload_template,
            group_listings,
        )

    def _build_action_url(self, current_url: str, action: str) -> str:
        if not action:
            raise PortalParseError("Portal form action is missing.")
        return urljoin(current_url, action)

    def _fetch_group_details(
        self,
        detail_url: str,
        referer_url: str,
        detail_payload_template: dict[str, str],
        group_listings: list[GroupListing],
    ) -> list[ScrapedGroup]:
        if not group_listings:
            return []

        max_workers = min(self.group_concurrency, len(group_listings))
        if max_workers == 1:
            worker_session = self._clone_worker_session()
            try:
                return [
                    self._fetch_group_detail(
                        worker_session,
                        detail_url,
                        referer_url,
                        detail_payload_template,
                        listing,
                    )
                    for listing in group_listings
                ]
            finally:
                self._close_session(worker_session)

        worker_local = threading.local()
        created_sessions: list[requests.Session] = []
        created_sessions_lock = threading.Lock()

        def get_worker_session():
            worker_session = getattr(worker_local, "session", None)
            if worker_session is None:
                worker_session = self._clone_worker_session()
                worker_local.session = worker_session
                with created_sessions_lock:
                    created_sessions.append(worker_session)
            return worker_session

        def fetch_group_detail(listing: GroupListing) -> ScrapedGroup:
            return self._fetch_group_detail(
                get_worker_session(),
                detail_url,
                referer_url,
                detail_payload_template,
                listing,
            )

        future_to_index = {}
        executor = ThreadPoolExecutor(max_workers=max_workers)
        try:
            for index, listing in enumerate(group_listings):
                future = executor.submit(
                    fetch_group_detail,
                    listing,
                )
                future_to_index[future] = index

            results: list[ScrapedGroup | None] = [None] * len(group_listings)
            pending = set(future_to_index)
            while pending:
                done, pending = wait(pending, return_when=FIRST_EXCEPTION)
                for future in done:
                    index = future_to_index[future]
                    results[index] = future.result()
        except Exception:
            for future in future_to_index:
                future.cancel()
            executor.shutdown(wait=True, cancel_futures=True)
            raise
        else:
            executor.shutdown(wait=True)
        finally:
            for worker_session in created_sessions:
                self._close_session(worker_session)

        return [result for result in results if result is not None]

    def _fetch_group_detail(
        self,
        session: requests.Session,
        detail_url: str,
        referer_url: str,
        detail_payload_template: dict[str, str],
        listing: GroupListing,
    ) -> ScrapedGroup:
        detail_payload = dict(detail_payload_template)
        detail_payload.update(
            {
                "__EVENTTARGET": listing.event_target,
                "__EVENTARGUMENT": "",
            }
        )
        detail_response = self._request_with_session(
            session,
            "post",
            detail_url,
            data=detail_payload,
            headers={"Referer": referer_url},
        )
        return parse_group_detail_html(detail_response.text)

    def _clone_worker_session(self) -> requests.Session:
        worker_session = requests.Session()
        worker_session.headers.update(getattr(self.session, "headers", {}))
        source_cookies = getattr(self.session, "cookies", None)
        if source_cookies is not None:
            worker_session.cookies.update(source_cookies)
        worker_session.auth = getattr(self.session, "auth", None)
        worker_session.proxies = dict(getattr(self.session, "proxies", {}))
        worker_session.verify = getattr(self.session, "verify", True)
        worker_session.cert = getattr(self.session, "cert", None)
        worker_session.stream = getattr(self.session, "stream", False)
        worker_session.trust_env = getattr(self.session, "trust_env", True)
        worker_session.max_redirects = getattr(
            self.session,
            "max_redirects",
            worker_session.max_redirects,
        )
        worker_session.hooks = {
            key: list(value)
            for key, value in getattr(self.session, "hooks", {}).items()
        }
        return worker_session

    def _close_session(self, session) -> None:
        close = getattr(session, "close", None)
        if callable(close):
            close()

    def _request(self, method: str, url: str, **kwargs):
        return self._request_with_session(self.session, method, url, **kwargs)

    def _request_with_session(self, session, method: str, url: str, **kwargs):
        last_error: Exception | None = None
        redacted_url = self._redact_url(url)
        for attempt in range(1, self.max_attempts + 1):
            try:
                response = getattr(session, method)(url, timeout=self.timeout, **kwargs)
                response.raise_for_status()
                return response
            except requests.RequestException as exc:
                last_error = exc
                if attempt == self.max_attempts:
                    break
                self.logger.warning(
                    "Portal request failed, retrying attempt %s/%s for %s %s.",
                    attempt,
                    self.max_attempts,
                    method.upper(),
                    redacted_url,
                )
                if self.backoff_seconds > 0:
                    time.sleep(self.backoff_seconds * attempt)
        raise PortalRequestError(
            f"Portal request failed after {self.max_attempts} attempts: "
            f"{method.upper()} {redacted_url}"
        ) from last_error

    def _redact_url(self, url: str) -> str:
        parsed = urlparse(url)
        if parsed.scheme and parsed.netloc:
            path = parsed.path or "/"
            return f"{parsed.scheme}://{parsed.netloc}{path}"
        return parsed.path or "/"

    def _match_profile_choice(
        self,
        profile_choices: dict[str, ProfileChoice],
        desired_label: str,
    ) -> ProfileChoice | None:
        if desired_label in profile_choices:
            return profile_choices[desired_label]
        desired_key = desired_label.strip().casefold()
        for label, choice in profile_choices.items():
            if label.strip().casefold() == desired_key:
                return choice
        return None


def _parse_group_header(soup: BeautifulSoup) -> GroupHeader:
    sede = soup.find(id="cphContenido_lblSede")
    province = ""
    group_code = ""
    if sede:
        parts = sede.get_text(strip=True).split("-")
        if len(parts) == 2:
            province = parts[0].strip()
            group_code = parts[1].strip()

    period = ""
    year = ""
    semester = soup.find(id="lblSem")
    if semester:
        text = semester.get_text(strip=True)
        if "Periodo:" in text:
            period_info = text.replace("Periodo:", "").strip()
            if "-" in period_info:
                period, year = [item.strip() for item in period_info.split("-", 1)]

    faculty = soup.find(id="cphContenido_LblFacultad")
    return GroupHeader(
        group_code=group_code,
        province=province,
        faculty=faculty.get_text(strip=True) if faculty else "",
        year=year,
        period=period,
    )


def _parse_group_sessions(soup: BeautifulSoup) -> list[SessionRecord]:
    day_map = {
        "LUNES": "MONDAY",
        "MARTES": "TUESDAY",
        "MIERCOLES": "WEDNESDAY",
        "MIÉRCOLES": "WEDNESDAY",
        "JUEVES": "THURSDAY",
        "VIERNES": "FRIDAY",
        "SABADO": "SATURDAY",
        "SÁBADO": "SATURDAY",
        "DOMINGO": "SUNDAY",
    }
    timetable = soup.find("table", id="cphContenido_gvHorario")
    if timetable is None:
        return []

    rows = timetable.find_all("tr")
    if not rows:
        return []
    header_cells = rows[0].find_all("th")
    day_names = [cell.get_text(strip=True).upper() for cell in header_cells[1:]]

    sessions: list[SessionRecord] = []
    for row in rows[1:]:
        cells = row.find_all("td")
        if not cells:
            continue
        time_slot = cells[0].get_text(strip=True)
        for index, cell in enumerate(cells[1:7]):
            if index >= len(day_names):
                break
            cell_text = " ".join(cell.stripped_strings)
            if not cell_text or cell_text == "&nbsp;":
                continue
            lines = list(cell.stripped_strings)
            if len(lines) >= 2:
                subject = lines[0].strip()
                classroom = lines[1].replace("aula", "").strip()
            else:
                subject = cell_text.strip()
                classroom = ""

            lab_code = extract_lab_code(subject)
            sessions.append(
                SessionRecord(
                    day=day_map.get(day_names[index], day_names[index]),
                    subject=subject,
                    session_type="Laboratory" if lab_code else "Theory",
                    classroom=classroom,
                    lab_code=lab_code,
                    time_slot=time_slot,
                )
            )
    return sessions


def _parse_subject_professors(soup: BeautifulSoup) -> list[SubjectProfessor]:
    detail_table = soup.find("table", id="cphContenido_Gvdetalle")
    if detail_table is None:
        return []

    subject_professors: list[SubjectProfessor] = []
    for row in detail_table.find_all("tr")[1:]:
        cells = row.find_all("td")
        if len(cells) < 5:
            continue
        subject_professors.append(
            SubjectProfessor(
                subject=cells[0].get_text(strip=True),
                subject_code=cells[1].get_text(strip=True),
                professor_name=cells[3].get_text(strip=True),
                professor_email=cells[4].get_text(strip=True),
            )
        )
    return subject_professors
