from __future__ import annotations

from dataclasses import dataclass
from datetime import time

from schedule_calculator.domain.models import ScheduleRequest, ScheduleResult
from schedule_calculator.domain.rules import session_time_bounds, time_to_minutes
from schedule_calculator.formatters import format_enrollment_label

DAY_SEQUENCE = (
    "MONDAY",
    "TUESDAY",
    "WEDNESDAY",
    "THURSDAY",
    "FRIDAY",
    "SATURDAY",
    "SUNDAY",
)
BASE_CALENDAR_DAYS = DAY_SEQUENCE[:6]
DAY_LABELS = {
    "MONDAY": "Mon",
    "TUESDAY": "Tue",
    "WEDNESDAY": "Wed",
    "THURSDAY": "Thu",
    "FRIDAY": "Fri",
    "SATURDAY": "Sat",
    "SUNDAY": "Sun",
}
SUBJECT_COLOR_PALETTE = (
    "#DCEBFA",
    "#F9DFC7",
    "#D9F2E3",
    "#F4E0F0",
    "#FFF1B8",
    "#E1DEFF",
    "#F9D7DF",
    "#D8F1EF",
    "#F4E7CF",
    "#DDE8C8",
)


@dataclass(slots=True)
class CalendarDay:
    key: str
    label: str


@dataclass(slots=True)
class CalendarLegendItem:
    subject_id: str
    subject_name: str
    group_code: str
    color_hex: str
    label: str


@dataclass(slots=True)
class CalendarBlock:
    day: str
    subject_id: str
    subject_name: str
    group_code: str
    session_type: str
    classroom: str
    lab_code: str | None
    start_time: time
    end_time: time
    start_minutes: int
    end_minutes: int
    color_hex: str
    label_lines: tuple[str, ...]

    @property
    def label(self) -> str:
        return "\n".join(self.label_lines)


@dataclass(slots=True)
class ScheduleCalendarView:
    days: list[CalendarDay]
    visible_start_minutes: int
    visible_end_minutes: int
    time_markers: list[int]
    legend: list[CalendarLegendItem]
    blocks: list[CalendarBlock]
    requested_province: str
    availability_start: time
    availability_end: time
    total_idle_minutes: int
    enrollment_summary: str


def build_schedule_calendar_view(
    request: ScheduleRequest,
    result: ScheduleResult,
) -> ScheduleCalendarView:
    if not result.chosen_enrollments:
        raise ValueError("Schedule result is missing chosen enrollments.")

    subject_order = {
        enrollment.subject_id: index
        for index, enrollment in enumerate(result.chosen_enrollments)
    }
    color_by_subject: dict[str, str] = {}
    legend: list[CalendarLegendItem] = []
    blocks: list[CalendarBlock] = []

    for index, enrollment in enumerate(result.chosen_enrollments):
        color_hex = color_by_subject.setdefault(
            enrollment.subject_id,
            SUBJECT_COLOR_PALETTE[index % len(SUBJECT_COLOR_PALETTE)],
        )
        legend.append(
            CalendarLegendItem(
                subject_id=enrollment.subject_id,
                subject_name=enrollment.subject_name,
                group_code=enrollment.group_code,
                color_hex=color_hex,
                label=format_enrollment_label(enrollment, include_subject_name=True),
            )
        )
        for session in enrollment.sessions:
            start_time, end_time = session_time_bounds(session)
            blocks.append(
                CalendarBlock(
                    day=session.day.upper(),
                    subject_id=enrollment.subject_id,
                    subject_name=enrollment.subject_name,
                    group_code=enrollment.group_code,
                    session_type=session.session_type,
                    classroom=session.classroom,
                    lab_code=session.lab_code,
                    start_time=start_time,
                    end_time=end_time,
                    start_minutes=time_to_minutes(start_time),
                    end_minutes=time_to_minutes(end_time),
                    color_hex=color_hex,
                    label_lines=_build_block_label_lines(
                        enrollment.subject_id,
                        enrollment.subject_name,
                        enrollment.group_code,
                        session.session_type,
                        session.classroom,
                        session.lab_code,
                        start_time,
                        end_time,
                    ),
                )
            )

    if not blocks:
        raise ValueError("Schedule result has no sessions to render.")

    days = _build_days(blocks)
    visible_start_minutes, visible_end_minutes = _calculate_visible_range(blocks)
    blocks.sort(
        key=lambda block: (
            _day_sort_key(block.day),
            block.start_minutes,
            block.end_minutes,
            subject_order.get(block.subject_id, len(subject_order)),
            block.group_code,
            block.session_type,
        )
    )

    return ScheduleCalendarView(
        days=days,
        visible_start_minutes=visible_start_minutes,
        visible_end_minutes=visible_end_minutes,
        time_markers=_build_time_markers(visible_start_minutes, visible_end_minutes),
        legend=legend,
        blocks=blocks,
        requested_province=request.desired_province.strip(),
        availability_start=request.available_start,
        availability_end=request.available_end,
        total_idle_minutes=result.total_idle_minutes,
        enrollment_summary=", ".join(item.label for item in legend),
    )


def minutes_to_label(total_minutes: int) -> str:
    hours = max(total_minutes, 0) // 60
    minutes = max(total_minutes, 0) % 60
    return f"{hours:02d}:{minutes:02d}"


def _build_days(blocks: list[CalendarBlock]) -> list[CalendarDay]:
    days = [
        CalendarDay(key=day_key, label=DAY_LABELS[day_key])
        for day_key in BASE_CALENDAR_DAYS
    ]
    present_days = {block.day for block in blocks}
    if "SUNDAY" in present_days:
        days.append(CalendarDay(key="SUNDAY", label=DAY_LABELS["SUNDAY"]))

    extra_days = sorted(day for day in present_days if day not in DAY_LABELS)
    for day in extra_days:
        days.append(CalendarDay(key=day, label=day.title()))
    return days


def _build_block_label_lines(
    subject_id: str,
    subject_name: str,
    group_code: str,
    session_type: str,
    classroom: str,
    lab_code: str | None,
    start_time: time,
    end_time: time,
) -> tuple[str, ...]:
    session_label = session_type.strip() or "Session"
    if lab_code:
        session_label = f"{session_label} ({lab_code})"
    subject_line = subject_id if not subject_name else f"{subject_id} {subject_name}"
    return (
        subject_line,
        f"Group: {group_code}",
        session_label,
        f"{start_time.strftime('%H:%M')}-{end_time.strftime('%H:%M')}",
        f"Classroom: {classroom or 'TBD'}",
    )


def _calculate_visible_range(blocks: list[CalendarBlock]) -> tuple[int, int]:
    earliest_start = min(block.start_minutes for block in blocks)
    latest_end = max(block.end_minutes for block in blocks)
    visible_start = (earliest_start // 30) * 30
    visible_end = ((latest_end + 29) // 30) * 30
    if visible_end <= visible_start:
        visible_end = visible_start + 30
    return visible_start, visible_end


def _build_time_markers(visible_start: int, visible_end: int) -> list[int]:
    markers = list(range(visible_start, visible_end + 1, 30))
    if markers[-1] != visible_end:
        markers.append(visible_end)
    return markers


def _day_sort_key(day: str) -> tuple[int, str]:
    try:
        return DAY_SEQUENCE.index(day), day
    except ValueError:
        return len(DAY_SEQUENCE), day
