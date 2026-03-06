from __future__ import annotations

from collections import defaultdict
from contextlib import contextmanager
from typing import Iterator

from schedule_calculator.domain.models import CourseGroup, ScrapedGroup, SessionRecord
from schedule_calculator.domain.rules import normalize_subject, parse_time_slot
from schedule_calculator.infrastructure.config import DatabaseConfig


def connect_postgres(config: DatabaseConfig):
    try:
        import psycopg2
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "psycopg2 is not installed. Install it to use the Postgres adapters."
        ) from exc

    return psycopg2.connect(config.dsn)


@contextmanager
def postgres_connection(config: DatabaseConfig) -> Iterator[object]:
    connection = connect_postgres(config)
    try:
        yield connection
    finally:
        connection.close()


class PostgresGroupCatalogRepository:
    def __init__(self, connection) -> None:
        self.connection = connection

    def list_groups_for_subject(self, subject_id: str) -> list[CourseGroup]:
        query = """
        SELECT cg.group_code,
               cg.province,
               cc.session_type,
               cc.lab_code,
               s.day,
               s.start_time,
               s.end_time,
               cs.classroom
        FROM course_class cc
        JOIN course_group cg ON cc.group_code = cg.group_code
        JOIN class_schedule cs ON cc.id_class = cs.id_class
        JOIN schedule s ON cs.id_schedule = s.id_schedule
        WHERE cc.subject_id = %s
        ORDER BY cg.group_code, s.day, s.start_time;
        """
        with self.connection.cursor() as cursor:
            cursor.execute(query, (subject_id,))
            rows = cursor.fetchall()

        groups: dict[str, CourseGroup] = {}
        for row in rows:
            (
                group_code,
                province,
                session_type,
                lab_code,
                day,
                start_time,
                end_time,
                classroom,
            ) = row
            if group_code not in groups:
                groups[group_code] = CourseGroup(
                    group_code=group_code,
                    subject_id=subject_id,
                    province=province,
                    sessions=[],
                )
            groups[group_code].sessions.append(
                SessionRecord(
                    day=day,
                    subject=subject_id,
                    session_type=session_type,
                    classroom=classroom,
                    lab_code=lab_code,
                    start_time=start_time,
                    end_time=end_time,
                )
            )
        return list(groups.values())


class PostgresGroupPersistenceRepository:
    def __init__(self, connection) -> None:
        self.connection = connection

    def is_group_processed(self, group_code: str) -> bool:
        with self.connection.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) FROM process_history WHERE group_code = %s",
                (group_code,),
            )
            return cursor.fetchone()[0] > 0

    def persist_group(self, group: ScrapedGroup) -> None:
        try:
            with self.connection.cursor() as cursor:
                faculty_id = self._get_or_create_faculty(cursor, group.header.faculty)
                cursor.execute(
                    "INSERT INTO course_group (group_code, province, id_faculty) VALUES (%s, %s, %s)",
                    (group.header.group_code, group.header.province, faculty_id),
                )

                subject_mapping = self._build_subject_mapping(cursor, group)
                class_mapping: dict[tuple[str, str, str | None, int | None], int] = {}

                for session in group.sessions:
                    start_time, end_time = parse_time_slot(session.time_slot or "")
                    mapping = subject_mapping[normalize_subject(session.subject)]
                    subject_code = mapping["subject_code"]
                    professor_id = (
                        mapping["professor_id"]
                        if session.session_type.lower() == "theory"
                        else None
                    )
                    lab_code = session.lab_code if session.session_type == "Laboratory" else None
                    class_key = (subject_code, session.session_type, lab_code, professor_id)

                    if class_key in class_mapping:
                        class_id = class_mapping[class_key]
                    else:
                        cursor.execute(
                            """
                            INSERT INTO course_class
                            (group_code, subject_id, session_type, lab_code, id_professor)
                            VALUES (%s, %s, %s, %s, %s)
                            RETURNING id_class
                            """,
                            (
                                group.header.group_code,
                                subject_code,
                                session.session_type,
                                lab_code,
                                professor_id,
                            ),
                        )
                        class_id = cursor.fetchone()[0]
                        class_mapping[class_key] = class_id

                    schedule_id = self._get_or_create_schedule(
                        cursor,
                        session.day,
                        start_time,
                        end_time,
                    )
                    cursor.execute(
                        "INSERT INTO class_schedule (id_class, id_schedule, classroom) VALUES (%s, %s, %s)",
                        (class_id, schedule_id, session.classroom),
                    )

                cursor.execute(
                    "INSERT INTO process_history (group_code, processed_at) VALUES (%s, NOW())",
                    (group.header.group_code,),
                )

            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise

    def _get_or_create_faculty(self, cursor, faculty_name: str) -> int:
        normalized_name = faculty_name.strip()
        cursor.execute(
            "SELECT id_faculty FROM faculty WHERE TRIM(faculty_name) = %s",
            (normalized_name,),
        )
        faculty = cursor.fetchone()
        if faculty:
            return faculty[0]
        cursor.execute(
            "INSERT INTO faculty (faculty_name) VALUES (%s) RETURNING id_faculty",
            (normalized_name,),
        )
        return cursor.fetchone()[0]

    def _build_subject_mapping(self, cursor, group: ScrapedGroup) -> dict[str, dict[str, int | None | str]]:
        subject_mapping: dict[str, dict[str, int | None | str]] = {}
        for subject_professor in group.subject_professors:
            subject_code = subject_professor.subject_code
            cursor.execute("SELECT subject_id FROM course_subject WHERE subject_id = %s", (subject_code,))
            if not cursor.fetchone():
                cursor.execute(
                    "INSERT INTO course_subject (subject_id, name) VALUES (%s, %s)",
                    (subject_code, subject_professor.subject),
                )

            professor_id = self._get_or_create_professor(
                cursor,
                subject_professor.professor_name,
                subject_professor.professor_email,
            )
            subject_mapping[normalize_subject(subject_professor.subject)] = {
                "subject_code": subject_code,
                "professor_id": professor_id,
            }
        return subject_mapping

    def _get_or_create_professor(
        self,
        cursor,
        professor_name: str,
        professor_email: str,
    ) -> int | None:
        if not professor_name and not professor_email:
            return None
        if professor_email:
            cursor.execute(
                "SELECT id_professor FROM professor WHERE email = %s",
                (professor_email,),
            )
            professor = cursor.fetchone()
            if professor:
                return professor[0]
            cursor.execute(
                "INSERT INTO professor (name, email) VALUES (%s, %s) RETURNING id_professor",
                (professor_name, professor_email),
            )
            return cursor.fetchone()[0]

        cursor.execute(
            "SELECT id_professor FROM professor WHERE name = %s AND (email IS NULL OR email = '')",
            (professor_name,),
        )
        professor = cursor.fetchone()
        if professor:
            return professor[0]
        cursor.execute(
            "INSERT INTO professor (name, email) VALUES (%s, %s) RETURNING id_professor",
            (professor_name, None),
        )
        return cursor.fetchone()[0]

    def _get_or_create_schedule(self, cursor, day: str, start_time, end_time) -> int:
        cursor.execute(
            "SELECT id_schedule FROM schedule WHERE day = %s AND start_time = %s AND end_time = %s",
            (day, start_time, end_time),
        )
        schedule = cursor.fetchone()
        if schedule:
            return schedule[0]
        cursor.execute(
            "INSERT INTO schedule (day, start_time, end_time) VALUES (%s, %s, %s) RETURNING id_schedule",
            (day, start_time, end_time),
        )
        return cursor.fetchone()[0]

