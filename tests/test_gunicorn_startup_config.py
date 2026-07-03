import os
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


class GunicornStartupConfigTests(unittest.TestCase):
    def _run_start_script_with_fake_gunicorn(self, extra_env=None):
        script = REPO_ROOT / "scripts/start-gunicorn.sh"
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            args_file = tmp / "gunicorn.args"
            fake_gunicorn = tmp / "gunicorn"
            fake_gunicorn.write_text(
                "#!/bin/sh\n" 'printf \'%s\\n\' "$@" > "$GUNICORN_ARGS_FILE"\n',
                encoding="utf-8",
            )
            fake_gunicorn.chmod(0o755)
            env = os.environ.copy()
            env.update(
                {
                    "PATH": f"{tmp}:{env.get('PATH', '')}",
                    "GUNICORN_ARGS_FILE": str(args_file),
                }
            )
            if extra_env:
                env.update(extra_env)
            result = subprocess.run(
                [str(script)],
                cwd=REPO_ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            args = args_file.read_text(encoding="utf-8").splitlines() if args_file.exists() else []
            return result, args

    def test_dockerfile_uses_configurable_gunicorn_start_script(self):
        dockerfile = _read("Dockerfile")

        self.assertIn("GUNICORN_WORKERS=1", dockerfile)
        self.assertIn("GUNICORN_THREADS=8", dockerfile)
        self.assertIn("GUNICORN_TIMEOUT=120", dockerfile)
        self.assertIn('CMD ["scripts/start-gunicorn.sh"]', dockerfile)
        self.assertNotIn('CMD ["gunicorn", "-w", "1"', dockerfile)
        self.assertIn("chmod +x /app/scripts/start-gunicorn.sh", dockerfile)

    def test_compose_exposes_gunicorn_concurrency_knobs(self):
        compose = _read("docker-compose.yml")

        self.assertIn('GUNICORN_WORKERS: "${GUNICORN_WORKERS:-1}"', compose)
        self.assertIn('GUNICORN_THREADS: "${GUNICORN_THREADS:-8}"', compose)
        self.assertIn('GUNICORN_TIMEOUT: "${GUNICORN_TIMEOUT:-120}"', compose)

    def test_start_script_keeps_single_worker_default_with_threads(self):
        script = _read("scripts/start-gunicorn.sh")

        self.assertIn(': "${GUNICORN_WORKERS:=1}"', script)
        self.assertIn(': "${GUNICORN_THREADS:=8}"', script)
        self.assertIn(': "${GUNICORN_TIMEOUT:=120}"', script)
        self.assertIn("--threads", script)
        self.assertIn("web_outlook_app:app", script)
        self.assertNotIn("--preload", script)
        self.assertIn("wait-message", script)

    def test_start_script_passes_default_threaded_gunicorn_args(self):
        result, args = self._run_start_script_with_fake_gunicorn()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            args,
            [
                "-w",
                "1",
                "--threads",
                "8",
                "-b",
                "0.0.0.0:5000",
                "--timeout",
                "120",
                "--access-logfile",
                "-",
                "web_outlook_app:app",
            ],
        )

    def test_start_script_allows_env_overrides(self):
        result, args = self._run_start_script_with_fake_gunicorn(
            {
                "GUNICORN_WORKERS": "2",
                "GUNICORN_THREADS": "12",
                "GUNICORN_TIMEOUT": "90",
                "GUNICORN_BIND": "127.0.0.1:5050",
                "GUNICORN_ACCESS_LOGFILE": "/tmp/access.log",
            }
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            args,
            [
                "-w",
                "2",
                "--threads",
                "12",
                "-b",
                "127.0.0.1:5050",
                "--timeout",
                "90",
                "--access-logfile",
                "/tmp/access.log",
                "web_outlook_app:app",
            ],
        )

    def test_start_script_rejects_zero_or_non_numeric_values(self):
        script = REPO_ROOT / "scripts/start-gunicorn.sh"
        self.assertTrue(script.stat().st_mode & 0o111)

        result, _args = self._run_start_script_with_fake_gunicorn({"GUNICORN_THREADS": "0"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("GUNICORN_THREADS must be a positive integer", result.stderr)

        result, _args = self._run_start_script_with_fake_gunicorn({"GUNICORN_WORKERS": "many"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("GUNICORN_WORKERS must be a positive integer", result.stderr)


if __name__ == "__main__":
    unittest.main()
