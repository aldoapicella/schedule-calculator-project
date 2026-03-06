from __future__ import annotations

import os
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

from schedule_calculator.infrastructure.config import (
    load_database_config,
    load_environment,
    load_portal_credentials,
)


class ConfigTests(unittest.TestCase):
    def test_load_environment_prefers_explicit_env_file_and_expands_placeholders(self) -> None:
        env_file = self._write_env_file(
            """
            POSTGRES_USER=file_user
            POSTGRES_PASSWORD=file_password
            POSTGRES_DB=file_db
            POSTGRES_URI=postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB}
            """
        )

        with mock.patch.dict(os.environ, {"POSTGRES_USER": "env_user"}, clear=True):
            env = load_environment(env_file)

        self.assertEqual(env["POSTGRES_USER"], "file_user")
        self.assertEqual(
            env["POSTGRES_URI"],
            "postgresql://file_user:file_password@postgres:5432/file_db",
        )

    def test_load_database_config_prefers_explicit_uri(self) -> None:
        env_file = self._write_env_file(
            """
            POSTGRES_URI=postgresql://custom:secret@db.example.com:5432/schedule
            POSTGRES_USER=ignored
            POSTGRES_PASSWORD=ignored
            POSTGRES_DB=ignored
            """
        )

        with mock.patch.dict(os.environ, {}, clear=True):
            config = load_database_config(env_file)

        self.assertEqual(config.dsn, "postgresql://custom:secret@db.example.com:5432/schedule")

    def test_load_database_config_builds_host_mode_dsn_from_components(self) -> None:
        env_file = self._write_env_file(
            """
            POSTGRES_USER=user
            POSTGRES_PASSWORD=password
            POSTGRES_DB=schedule_data
            POSTGRES_HOST=localhost
            POSTGRES_PORT=5432
            """
        )

        with mock.patch.dict(os.environ, {}, clear=True):
            config = load_database_config(env_file)

        self.assertEqual(
            config.dsn,
            "postgresql://user:password@localhost:5432/schedule_data",
        )

    def test_load_database_config_builds_docker_mode_dsn_from_components(self) -> None:
        env_file = self._write_env_file(
            """
            POSTGRES_USER=user
            POSTGRES_PASSWORD=password
            POSTGRES_DB=schedule_data
            POSTGRES_HOST=postgres
            POSTGRES_PORT=5432
            """
        )

        with mock.patch.dict(os.environ, {}, clear=True):
            config = load_database_config(env_file)

        self.assertEqual(
            config.dsn,
            "postgresql://user:password@postgres:5432/schedule_data",
        )

    def test_load_portal_credentials_reads_profile_label(self) -> None:
        env_file = self._write_env_file(
            """
            UTP_USERNAME=20-70-5158
            UTP_PASSWORD=secret
            UTP_PROFILE_LABEL=Servicios
            """
        )

        with mock.patch.dict(os.environ, {}, clear=True):
            credentials = load_portal_credentials(env_file)

        self.assertEqual(credentials.username, "20-70-5158")
        self.assertEqual(credentials.password, "secret")
        self.assertEqual(credentials.profile_label, "Servicios")

    def _write_env_file(self, contents: str) -> Path:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        path = Path(temp_dir.name) / ".env"
        path.write_text(textwrap.dedent(contents).strip() + "\n", encoding="utf-8")
        return path


if __name__ == "__main__":
    unittest.main()
