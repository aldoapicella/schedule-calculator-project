from __future__ import annotations

from dataclasses import dataclass, field
from datetime import time
from typing import Any


@dataclass(slots=True)
class PortalCredentials:
    username: str
    password: str
    profile_label: str = "Estudiantes"


@dataclass(slots=True)
class PortalSessionState:
    viewstate: str = ""
    eventvalidation: str = ""
    viewstategenerator: str = ""
    action: str = ""
    eventtarget: str = ""
    eventargument: str = ""
    lastfocus: str = ""
    extra_fields: dict[str, str] = field(default_factory=dict)

    def as_payload(self) -> dict[str, str]:
        payload = dict(self.extra_fields)
        payload["__VIEWSTATE"] = self.viewstate
        payload["__EVENTVALIDATION"] = self.eventvalidation
        payload["__VIEWSTATEGENERATOR"] = self.viewstategenerator
        payload["__EVENTTARGET"] = self.eventtarget
        payload["__EVENTARGUMENT"] = self.eventargument
        if self.lastfocus:
            payload["__LASTFOCUS"] = self.lastfocus
        return payload


@dataclass(slots=True)
class GroupHeader:
    group_code: str = ""
    province: str = ""
    faculty: str = ""
    year: str = ""
    period: str = ""

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "GroupHeader":
        payload = payload or {}
        return cls(
            group_code=str(payload.get("group_code", "")).strip(),
            province=str(payload.get("province", "")).strip(),
            faculty=str(payload.get("faculty", "")).strip(),
            year=str(payload.get("year", "")).strip(),
            period=str(payload.get("period", "")).strip(),
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "group_code": self.group_code,
            "province": self.province,
            "faculty": self.faculty,
            "year": self.year,
            "period": self.period,
        }


@dataclass(slots=True)
class SessionRecord:
    day: str
    subject: str = ""
    session_type: str = ""
    classroom: str = ""
    lab_code: str | None = None
    time_slot: str | None = None
    start_time: time | None = None
    end_time: time | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SessionRecord":
        start_time = payload.get("start_time")
        end_time = payload.get("end_time")
        return cls(
            day=str(payload.get("day", "")).strip(),
            subject=str(payload.get("subject", "")).strip(),
            session_type=str(payload.get("session_type", "")).strip(),
            classroom=str(payload.get("classroom", "")).strip(),
            lab_code=(str(payload["lab_code"]).strip() if payload.get("lab_code") else None),
            time_slot=(str(payload["time_slot"]).strip() if payload.get("time_slot") else None),
            start_time=start_time if isinstance(start_time, time) else None,
            end_time=end_time if isinstance(end_time, time) else None,
        )

    def to_scraped_dict(self) -> dict[str, str]:
        payload = {
            "day": self.day,
            "time_slot": self.time_slot or "",
            "subject": self.subject,
            "session_type": self.session_type,
            "classroom": self.classroom,
        }
        if self.lab_code:
            payload["lab_code"] = self.lab_code
        return payload


@dataclass(slots=True)
class SubjectProfessor:
    subject: str
    subject_code: str
    professor_name: str = ""
    professor_email: str = ""

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SubjectProfessor":
        professor = payload.get("professor") or {}
        return cls(
            subject=str(payload.get("subject", "")).strip(),
            subject_code=str(payload.get("subject_code", "")).strip(),
            professor_name=str(professor.get("name", "")).strip(),
            professor_email=str(professor.get("email", "")).strip(),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject": self.subject,
            "subject_code": self.subject_code,
            "professor": {
                "name": self.professor_name,
                "email": self.professor_email,
            },
        }


@dataclass(slots=True)
class ScrapedGroup:
    header: GroupHeader
    sessions: list[SessionRecord]
    subject_professors: list[SubjectProfessor]

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ScrapedGroup":
        return cls(
            header=GroupHeader.from_dict(payload.get("header")),
            sessions=[SessionRecord.from_dict(session) for session in payload.get("sessions", [])],
            subject_professors=[
                SubjectProfessor.from_dict(subject_professor)
                for subject_professor in payload.get("subject_professors", [])
            ],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "header": self.header.to_dict(),
            "sessions": [session.to_scraped_dict() for session in self.sessions],
            "subject_professors": [
                subject_professor.to_dict() for subject_professor in self.subject_professors
            ],
        }


@dataclass(slots=True)
class CourseGroup:
    group_code: str
    subject_id: str
    province: str
    sessions: list[SessionRecord]
    subject_name: str = ""


@dataclass(slots=True)
class CandidateEnrollment:
    group_code: str
    subject_id: str
    province: str
    sessions: list[SessionRecord]
    subject_name: str = ""


@dataclass(slots=True)
class ScheduleRequest:
    desired_subjects: list[str]
    required_subjects: list[str]
    available_start: time
    available_end: time
    desired_province: str


@dataclass(slots=True)
class ScheduleResult:
    chosen_enrollments: list[CandidateEnrollment]
    final_schedule: list[SessionRecord]
    total_idle_minutes: int
