from __future__ import annotations

import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class CliScriptTests(unittest.TestCase):
    def test_help_output_exposes_verbose_flag_on_all_entrypoints(self) -> None:
        for script in (
            PROJECT_ROOT / "scrape_utp.py",
            PROJECT_ROOT / "data_extractor" / "inserter.py",
            PROJECT_ROOT / "data_extractor" / "calculator.py",
        ):
            completed = self._run_script(script, ["--help"])
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("--verbose", completed.stdout)

    def test_scraper_missing_credentials_exits_with_config_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env_file = Path(temp_dir) / ".env"
            env_file.write_text(
                "UTP_BASE_URL=https://matricula.utp.ac.pa/\n"
                "UTP_USERNAME=\n"
                "UTP_PASSWORD=\n",
                encoding="utf-8",
            )

            completed = self._run_script(
                PROJECT_ROOT / "scrape_utp.py",
                ["--subject-ids", "0698", "--env-file", str(env_file)],
                cwd=temp_dir,
            )

            self.assertEqual(completed.returncode, 2, completed.stderr)
            self.assertFalse((Path(temp_dir) / "scrape_utp.log").exists())

    def test_scraper_rejects_empty_subject_ids_as_usage_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env_file = Path(temp_dir) / ".env"
            env_file.write_text(
                "UTP_USERNAME=user\nUTP_PASSWORD=secret\nUTP_BASE_URL=https://matricula.utp.ac.pa/\n",
                encoding="utf-8",
            )

            completed = self._run_script(
                PROJECT_ROOT / "scrape_utp.py",
                ["--subject-ids", " ,, ", "--env-file", str(env_file)],
                cwd=temp_dir,
            )

            self.assertEqual(completed.returncode, 2, completed.stderr)
            self.assertIn("At least one subject ID is required", completed.stderr)

    def test_scraper_help_output_exposes_group_concurrency_flag(self) -> None:
        completed = self._run_script(PROJECT_ROOT / "scrape_utp.py", ["--help"])

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("--group-concurrency", completed.stdout)

    def test_scraper_rejects_non_positive_group_concurrency(self) -> None:
        completed = self._run_script(
            PROJECT_ROOT / "scrape_utp.py",
            ["--subject-ids", "0698", "--group-concurrency", "0"],
        )

        self.assertEqual(completed.returncode, 2, completed.stderr)
        self.assertIn("group concurrency must be at least 1", completed.stderr)

    def test_inserter_missing_input_exits_with_runtime_failure_without_default_log_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            completed = self._run_script(
                PROJECT_ROOT / "data_extractor" / "inserter.py",
                ["--input", str(Path(temp_dir) / "missing.json")],
                cwd=temp_dir,
            )

            self.assertEqual(completed.returncode, 1, completed.stderr)
            self.assertFalse((Path(temp_dir) / "insertion.log").exists())

    def test_calculator_missing_db_config_exits_with_config_error_without_default_log_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env_file = Path(temp_dir) / ".env"
            env_file.write_text(
                "POSTGRES_URI=\n"
                "POSTGRES_USER=\n"
                "POSTGRES_PASSWORD=\n"
                "POSTGRES_DB=\n"
                "POSTGRES_HOST=\n"
                "POSTGRES_PORT=\n",
                encoding="utf-8",
            )

            completed = self._run_script(
                PROJECT_ROOT / "data_extractor" / "calculator.py",
                [
                    "--subjects",
                    "0698,0709",
                    "--available-start",
                    "17:00",
                    "--available-end",
                    "23:00",
                    "--province",
                    "PANAMÁ",
                    "--env-file",
                    str(env_file),
                ],
                cwd=temp_dir,
            )

            self.assertEqual(completed.returncode, 2, completed.stderr)
            self.assertFalse((Path(temp_dir) / "schedule.log").exists())

    def _run_script(
        self,
        script_path: Path,
        args: list[str],
        *,
        cwd: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(script_path), *args],
            cwd=cwd or str(PROJECT_ROOT),
            text=True,
            capture_output=True,
            check=False,
        )


if __name__ == "__main__":
    unittest.main()
