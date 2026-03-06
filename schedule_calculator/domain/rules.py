from __future__ import annotations

import re
from datetime import datetime, time
from typing import Iterable, Sequence, TypeVar

from .models import CandidateEnrollment, CourseGroup, SessionRecord

ALLOWED_PROVINCES = {
    "AZUERO",
    "BOCAS DEL TORO",
    "CHIRIQUI",
    "CHIRIQUÍ",
    "COCLE",
    "COCLÉ",
    "COLON",
    "COLÓN",
    "PANAMA",
    "PANAMÁ",
    "PANAMA OESTE",
    "PANAMÁ OESTE",
    "VERAGUAS",
}

LAB_SUBJECT_PATTERN = re.compile(r"\(([A-Z])\s*\)")

T = TypeVar("T")


def normalize_subject(subject_name: str | None) -> str:
    if not subject_name:
        return ""
    normalized = LAB_SUBJECT_PATTERN.sub("", subject_name)
    return normalized.strip().upper()


def extract_lab_code(subject_name: str | None) -> str | None:
    if not subject_name:
        return None
    match = LAB_SUBJECT_PATTERN.search(subject_name)
    if not match:
        return None
    return match.group(1)


def is_virtual_class(classroom: str | None) -> bool:
    if not classroom:
        return False
    room = classroom.strip().upper()
    return room == "VVIRT" or "DIS" in room


def parse_time_slot(time_slot: str) -> tuple[time, time]:
    ts = time_slot.replace(" ", "").replace(".", "")
    if ts.endswith("AM"):
        period = "AM"
    elif ts.endswith("PM"):
        period = "PM"
    else:
        raise ValueError(f"Time slot does not end with AM or PM: {time_slot}")

    parts = ts.split("-")
    if len(parts) != 2:
        raise ValueError(f"Invalid time_slot format: {time_slot}")

    start_str, end_str = parts
    if not (start_str.endswith("AM") or start_str.endswith("PM")):
        start_str = f"{start_str}{period}"

    start_time = datetime.strptime(start_str, "%I:%M%p").time()
    end_time = datetime.strptime(end_str, "%I:%M%p").time()
    return start_time, end_time


def time_to_minutes(value: time) -> int:
    return value.hour * 60 + value.minute


def session_time_bounds(session: SessionRecord) -> tuple[time, time]:
    if session.start_time and session.end_time:
        return session.start_time, session.end_time
    if session.time_slot:
        return parse_time_slot(session.time_slot)
    raise ValueError("Session is missing time data.")


def sessions_conflict(sessions: Sequence[SessionRecord]) -> bool:
    schedule_by_day: dict[str, list[tuple[int, int]]] = {}
    for session in sessions:
        day = session.day.upper()
        start_time, end_time = session_time_bounds(session)
        schedule_by_day.setdefault(day, []).append(
            (time_to_minutes(start_time), time_to_minutes(end_time))
        )
    for intervals in schedule_by_day.values():
        intervals.sort()
        for index in range(1, len(intervals)):
            if intervals[index][0] < intervals[index - 1][1]:
                return True
    return False


def get_conflict_details(sessions: Sequence[SessionRecord]) -> list[str]:
    details: list[str] = []
    sessions_by_day: dict[str, list[tuple[SessionRecord, int, int]]] = {}
    for session in sessions:
        day = session.day.upper()
        start_time, end_time = session_time_bounds(session)
        sessions_by_day.setdefault(day, []).append(
            (session, time_to_minutes(start_time), time_to_minutes(end_time))
        )
    for day, day_sessions in sessions_by_day.items():
        day_sessions.sort(key=lambda item: item[1])
        for index in range(1, len(day_sessions)):
            previous, previous_start, previous_end = day_sessions[index - 1]
            current, current_start, current_end = day_sessions[index]
            if current_start < previous_end:
                prev_start_time, prev_end_time = session_time_bounds(previous)
                current_start_time, current_end_time = session_time_bounds(current)
                details.append(
                    "On "
                    f"{day}: {prev_start_time.strftime('%H:%M')}-{prev_end_time.strftime('%H:%M')} "
                    f"overlaps with {current_start_time.strftime('%H:%M')}-{current_end_time.strftime('%H:%M')}"
                )
    return details


def schedule_within_available(
    sessions: Sequence[SessionRecord], available_start: time, available_end: time
) -> bool:
    available_start_minutes = time_to_minutes(available_start)
    available_end_minutes = time_to_minutes(available_end)
    for session in sessions:
        start_time, end_time = session_time_bounds(session)
        start_minutes = time_to_minutes(start_time)
        end_minutes = time_to_minutes(end_time)
        if start_minutes < available_start_minutes or end_minutes > available_end_minutes:
            return False
    return True


def get_available_violations(
    sessions: Sequence[SessionRecord], available_start: time, available_end: time
) -> list[str]:
    available_start_minutes = time_to_minutes(available_start)
    available_end_minutes = time_to_minutes(available_end)
    violations: list[str] = []
    for session in sessions:
        start_time, end_time = session_time_bounds(session)
        start_minutes = time_to_minutes(start_time)
        end_minutes = time_to_minutes(end_time)
        if start_minutes < available_start_minutes or end_minutes > available_end_minutes:
            violations.append(
                f"{session.day} session {start_time.strftime('%H:%M')}-{end_time.strftime('%H:%M')} "
                f"is outside available hours ({available_start.strftime('%H:%M')}-"
                f"{available_end.strftime('%H:%M')})"
            )
    return violations


def total_idle_time(
    sessions: Sequence[SessionRecord], available_start: time, available_end: time
) -> int:
    idle = 0
    available_start_minutes = time_to_minutes(available_start)
    available_end_minutes = time_to_minutes(available_end)
    sessions_by_day: dict[str, list[tuple[int, int]]] = {}
    for session in sessions:
        day = session.day.upper()
        start_time, end_time = session_time_bounds(session)
        sessions_by_day.setdefault(day, []).append(
            (time_to_minutes(start_time), time_to_minutes(end_time))
        )
    for intervals in sessions_by_day.values():
        intervals.sort()
        duration = sum(end - start for start, end in intervals)
        idle += available_end_minutes - available_start_minutes - duration
    return idle


def theory_lab_consistency(group: CourseGroup | CandidateEnrollment) -> bool:
    has_lab = any(session.session_type.lower() == "laboratory" for session in group.sessions)
    if not has_lab:
        return True
    return any(session.session_type.lower() == "theory" for session in group.sessions)


def all_sessions_virtual(sessions: Sequence[SessionRecord]) -> bool:
    return all(is_virtual_class(session.classroom) for session in sessions)


def split_group_enrollments(group: CourseGroup) -> list[CandidateEnrollment]:
    theory_sessions = [
        session for session in group.sessions if session.session_type.lower() == "theory"
    ]
    lab_sessions = [
        session for session in group.sessions if session.session_type.lower() == "laboratory"
    ]
    if not lab_sessions:
        return [
            CandidateEnrollment(
                group_code=group.group_code,
                subject_id=group.subject_id,
                province=group.province,
                sessions=list(group.sessions),
            )
        ]
    if not theory_sessions:
        return []

    labs_by_code: dict[str, list[SessionRecord]] = {}
    for lab in lab_sessions:
        code = lab.lab_code or ""
        labs_by_code.setdefault(code, []).append(lab)

    enrollments: list[CandidateEnrollment] = []
    for labs in labs_by_code.values():
        enrollments.append(
            CandidateEnrollment(
                group_code=group.group_code,
                subject_id=group.subject_id,
                province=group.province,
                sessions=theory_sessions + labs,
            )
        )
    return enrollments


def ensure_allowed_province(province: str) -> None:
    normalized = province.strip().upper()
    if normalized not in ALLOWED_PROVINCES:
        raise ValueError(
            f"Province '{province}' is not allowed. Allowed: {sorted(ALLOWED_PROVINCES)}"
        )


def unique_preserve_order(values: Iterable[T]) -> list[T]:
    return list(dict.fromkeys(values))
