from __future__ import annotations

import copy
import logging

from schedule_calculator.application.interfaces import GroupCatalogRepository
from schedule_calculator.domain.models import ScheduleRequest, ScheduleResult
from schedule_calculator.domain.rules import (
    all_sessions_virtual,
    get_available_violations,
    get_conflict_details,
    schedule_within_available,
    sessions_conflict,
    split_group_enrollments,
    theory_lab_consistency,
    total_idle_time,
    unique_preserve_order,
)


class SchedulerService:
    def __init__(
        self,
        repository: GroupCatalogRepository,
        logger: logging.Logger | None = None,
    ) -> None:
        self.repository = repository
        self.logger = logger or logging.getLogger(__name__)

    def find_best_schedule(self, request: ScheduleRequest) -> ScheduleResult | None:
        desired_subjects = [subject for subject in unique_preserve_order(request.desired_subjects) if subject]
        required_subjects = set(subject for subject in request.required_subjects if subject)

        groups_by_subject = {}
        for subject_id in desired_subjects:
            candidate_groups = self.repository.list_groups_for_subject(subject_id)
            filtered_groups = []
            for group in candidate_groups:
                province_matches = group.province.upper() == request.desired_province.upper()
                if province_matches or all_sessions_virtual(group.sessions):
                    filtered_groups.append(group)
                else:
                    self.logger.info(
                        "Group %s for subject %s rejected: province %s does not match and "
                        "contains physical sessions.",
                        group.group_code,
                        subject_id,
                        group.province,
                    )

            consistent_groups = [
                group for group in filtered_groups if theory_lab_consistency(group)
            ]
            enrollments = []
            for group in consistent_groups:
                split_enrollments = split_group_enrollments(group)
                if not split_enrollments and any(
                    session.session_type.lower() == "laboratory" for session in group.sessions
                ):
                    self.logger.info(
                        "Group %s for subject %s has labs but no theory. Skipping.",
                        group.group_code,
                        subject_id,
                    )
                enrollments.extend(split_enrollments)

            groups_by_subject[subject_id] = enrollments
            self.logger.info(
                "Subject %s: %s candidate enrollments available.",
                subject_id,
                len(enrollments),
            )

        best_solution: ScheduleResult | None = None
        best_subject_count = 0
        best_idle: int | None = None

        def backtrack(index: int, current_sessions, chosen_enrollments) -> None:
            nonlocal best_solution, best_subject_count, best_idle
            enrollment_str = ", ".join(
                f"{enrollment.subject_id}:{enrollment.group_code}"
                for enrollment in chosen_enrollments
            )
            self.logger.debug(
                "Backtracking: index=%s, chosen_enrollments=[%s], current sessions count=%s",
                index,
                enrollment_str,
                len(current_sessions),
            )

            enrolled_subjects = {enrollment.subject_id for enrollment in chosen_enrollments}
            if len(chosen_enrollments) >= 2 and required_subjects.issubset(enrolled_subjects):
                if not sessions_conflict(current_sessions) and schedule_within_available(
                    current_sessions,
                    request.available_start,
                    request.available_end,
                ):
                    current_idle = total_idle_time(
                        current_sessions,
                        request.available_start,
                        request.available_end,
                    )
                    if (
                        len(chosen_enrollments) > best_subject_count
                        or (
                            len(chosen_enrollments) == best_subject_count
                            and (best_idle is None or current_idle < best_idle)
                        )
                    ):
                        best_subject_count = len(chosen_enrollments)
                        best_idle = current_idle
                        best_solution = ScheduleResult(
                            chosen_enrollments=copy.deepcopy(chosen_enrollments),
                            final_schedule=copy.deepcopy(current_sessions),
                            total_idle_minutes=current_idle,
                        )
                        self.logger.debug(
                            "New best solution: %s subjects, idle time %s minutes. Enrollments: %s",
                            best_subject_count,
                            best_idle,
                            enrollment_str,
                        )

            if index >= len(desired_subjects):
                return

            subject_id = desired_subjects[index]
            for enrollment in groups_by_subject.get(subject_id, []):
                new_sessions = current_sessions + enrollment.sessions
                if sessions_conflict(new_sessions):
                    self.logger.info(
                        "Combination rejected: Adding enrollment %s for subject %s causes "
                        "conflicts: %s. Skipping.",
                        enrollment.group_code,
                        subject_id,
                        get_conflict_details(new_sessions),
                    )
                    continue
                if not schedule_within_available(
                    new_sessions, request.available_start, request.available_end
                ):
                    self.logger.info(
                        "Combination rejected: Adding enrollment %s for subject %s places "
                        "sessions outside available hours: %s. Skipping.",
                        enrollment.group_code,
                        subject_id,
                        get_available_violations(
                            new_sessions,
                            request.available_start,
                            request.available_end,
                        ),
                    )
                    continue
                chosen_enrollments.append(enrollment)
                backtrack(index + 1, new_sessions, chosen_enrollments)
                chosen_enrollments.pop()

            backtrack(index + 1, current_sessions, chosen_enrollments)

        backtrack(0, [], [])
        return best_solution

