from __future__ import annotations

from typing import Protocol, Sequence

from schedule_calculator.domain.models import (
    CourseGroup,
    PortalCredentials,
    ScrapedGroup,
)


class GroupCatalogRepository(Protocol):
    def list_groups_for_subject(self, subject_id: str) -> list[CourseGroup]:
        ...


class GroupPersistenceRepository(Protocol):
    def is_group_processed(self, group_code: str) -> bool:
        ...

    def persist_group(self, group: ScrapedGroup) -> None:
        ...


class PortalClient(Protocol):
    def authenticate(self, credentials: PortalCredentials) -> None:
        ...

    def fetch_groups_for_subject(self, subject_id: str) -> list[ScrapedGroup]:
        ...

