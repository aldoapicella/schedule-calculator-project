from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from schedule_calculator.domain.models import PortalCredentials

ENV_VAR_PATTERN = re.compile(r"\$\{([^}]+)\}")


@dataclass(slots=True)
class DatabaseConfig:
    dsn: str


def load_environment(env_path: str | Path | None = None) -> dict[str, str]:
    path = Path(env_path) if env_path else Path(__file__).resolve().parents[2] / ".env"
    raw_values: dict[str, str] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            raw_values[key.strip()] = value.strip()

    resolution_context = {**raw_values, **os.environ}
    resolved_values = {
        key: _expand_value(value, resolution_context) for key, value in raw_values.items()
    }
    return {**resolved_values, **os.environ}


def load_database_config(env_path: str | Path | None = None) -> DatabaseConfig:
    env = load_environment(env_path)
    dsn = env.get("POSTGRES_URI", "").strip()
    if dsn:
        return DatabaseConfig(dsn=dsn)

    user = env.get("POSTGRES_USER", "").strip()
    password = env.get("POSTGRES_PASSWORD", "").strip()
    database = env.get("POSTGRES_DB", "").strip()
    host = env.get("POSTGRES_HOST", "localhost").strip() or "localhost"
    port = env.get("POSTGRES_PORT", "5432").strip() or "5432"

    if not user or not database:
        raise ValueError(
            "Database configuration is missing. Set POSTGRES_URI or "
            "POSTGRES_USER/POSTGRES_PASSWORD/POSTGRES_DB."
        )

    return DatabaseConfig(dsn=f"postgresql://{user}:{password}@{host}:{port}/{database}")


def load_portal_credentials(env_path: str | Path | None = None) -> PortalCredentials:
    env = load_environment(env_path)
    username = env.get("UTP_USERNAME", "").strip()
    password = env.get("UTP_PASSWORD", "").strip()
    profile_label = env.get("UTP_PROFILE_LABEL", "Estudiantes").strip() or "Estudiantes"
    if not username or not password:
        raise ValueError("Portal credentials are missing. Set UTP_USERNAME and UTP_PASSWORD.")
    return PortalCredentials(username=username, password=password, profile_label=profile_label)


def load_portal_base_url(env_path: str | Path | None = None) -> str:
    env = load_environment(env_path)
    return env.get("UTP_BASE_URL", "https://matricula.utp.ac.pa/").strip()


def _expand_value(value: str, context: dict[str, str]) -> str:
    expanded = value
    for _ in range(10):
        replacement = ENV_VAR_PATTERN.sub(lambda match: context.get(match.group(1), ""), expanded)
        if replacement == expanded:
            break
        expanded = replacement
    return expanded

