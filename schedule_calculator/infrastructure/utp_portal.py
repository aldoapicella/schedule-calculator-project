from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable
from urllib.parse import urljoin

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


def parse_portal_state(html: str, form_id: str) -> PortalSessionState:
    soup = BeautifulSoup(html, "html.parser")
    form = soup.find("form", {"id": form_id})
    if form is None:
        raise ValueError(f"Unable to find form '{form_id}'.")

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
    soup = BeautifulSoup(html, "html.parser")
    options: dict[str, str] = {}
    for input_tag in soup.find_all("input", {"type": "radio"}):
        name = input_tag.get("name", "")
        if "rblPerfiles" not in name:
            continue
        input_id = input_tag.get("id", "")
        label = soup.find("label", {"for": input_id})
        label_text = label.get_text(strip=True) if label else input_tag.get("value", "").strip()
        options[label_text] = input_tag.get("value", "").strip()
    return options


def extract_group_list_url(html: str, base_url: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    group_list_link = soup.find("a", {"id": "mListag"})
    if group_list_link is None or not group_list_link.get("href"):
        raise ValueError("Unable to find group list link.")
    href = group_list_link["href"].replace("../../../../", "")
    return urljoin(base_url, href).replace(".aspx", "")


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
        groups.append(GroupListing(event_target=href.split("'")[1]))
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
    ) -> None:
        self.base_url = base_url.rstrip("/") + "/"
        self.session = session or requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)
        self.timeout = timeout
        self.group_list_url: str | None = None

    def authenticate(self, credentials: PortalCredentials) -> None:
        login_response = self.session.get(self.base_url, timeout=self.timeout)
        login_response.raise_for_status()
        login_state = parse_portal_state(login_response.text, "ctl01")

        login_url = self._build_action_url("Session/Cuenta/Validar", login_state.action)
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

        profile_response = self.session.post(
            login_url,
            data=login_payload,
            timeout=self.timeout,
        )
        profile_response.raise_for_status()
        profile_state = parse_portal_state(profile_response.text, "ctl01")
        profile_options = parse_profile_options(profile_response.text)

        if credentials.profile_label not in profile_options:
            raise ValueError(
                f"Profile '{credentials.profile_label}' not found. Available: {sorted(profile_options)}"
            )

        profile_url = self._build_action_url("usuario/cuenta/perfiles/2025", profile_state.action)
        profile_payload = profile_state.as_payload()
        profile_payload.update(
            {
                "__EVENTTARGET": "",
                "__EVENTARGUMENT": "",
                "ctl00$MainContent$rblPerfiles": profile_options[credentials.profile_label],
            }
        )
        dashboard_response = self.session.post(
            profile_url,
            data=profile_payload,
            timeout=self.timeout,
        )
        dashboard_response.raise_for_status()
        self.group_list_url = extract_group_list_url(dashboard_response.text, self.base_url)

    def fetch_groups_for_subject(self, subject_id: str) -> list[ScrapedGroup]:
        if not self.group_list_url:
            raise RuntimeError("Portal client is not authenticated.")

        selection_response = self.session.get(self.group_list_url, timeout=self.timeout)
        selection_response.raise_for_status()
        selection_state = parse_portal_state(selection_response.text, "frmMaster")

        subject_payload = selection_state.as_payload()
        subject_payload.update(
            {
                "__EVENTTARGET": "ctl00$cphContenido$btnEnviar",
                "__EVENTARGUMENT": "",
                "ctl00$cphContenido$lista": "Rbasigdelplan",
                "ctl00$cphContenido$ddlasignaturas": subject_id,
            }
        )
        groups_response = self.session.post(
            self.group_list_url,
            data=subject_payload,
            timeout=self.timeout,
        )
        groups_response.raise_for_status()
        groups_state = parse_portal_state(groups_response.text, "frmMaster")
        group_listings = parse_group_rows(groups_response.text)

        scraped_groups: list[ScrapedGroup] = []
        for listing in group_listings:
            detail_payload = groups_state.as_payload()
            detail_payload.update(
                {
                    "__EVENTTARGET": listing.event_target,
                    "__EVENTARGUMENT": "",
                }
            )
            detail_response = self.session.post(
                self.group_list_url,
                data=detail_payload,
                timeout=self.timeout,
            )
            detail_response.raise_for_status()
            scraped_groups.append(parse_group_detail_html(detail_response.text))
        return scraped_groups

    def _build_action_url(self, prefix: str, action: str) -> str:
        action_fragment = action.lstrip("./")
        return urljoin(self.base_url, f"{prefix}/{action_fragment}")


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
