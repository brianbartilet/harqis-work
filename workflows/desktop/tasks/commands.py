import os, subprocess
from pathlib import Path

from core.apps.sprout.app.celery import SPROUT
from core.apps.es_logging.app.elasticsearch import log_result
from core.utilities.files import copy_files_any
from apps.rainmeter.references.helpers.settings import set_rainmeter_always_on_top
from apps.rainmeter.references.helpers.config_builder import _refresh_app


@SPROUT.task()
@log_result()
def git_pull_on_paths() -> str:

    def git_pull_all(paths: list[str]) -> dict:
        """
        Runs `git pull` for each path in the list.

        Args:
            paths (list[str]): List of local git repo directories.

        Returns:
            dict: {path: (success: bool, output: str)}
        """
        results = {}

        for path in paths:
            if not os.path.isdir(path):
                results[path] = (False, "Path not found")
                continue

            try:
                # Run git pull inside the directory
                result = subprocess.run(
                    ["git", "pull"],
                    cwd=path,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True
                )

                success = result.returncode == 0
                output = result.stdout if success else result.stderr

                results[path] = (success, output)

                print(f"\n=== {path} ===")
                print(output)

            except Exception as e:
                results[path] = (False, str(e))
                print(f"\nError pulling {path}: {e}")

        return results

    pull_list = [
        'C:/Users/brian/GIT/run/harqis-work'
    ]

    git_pull_all(pull_list)

    return " ".join(x for x in pull_list)


@SPROUT.task()
@log_result()
def copy_files_targeted() -> str:
    files = [
        (r"C:\Users\brian\GIT\harqis-work\.env\credentials.json", r"C:\Users\brian\GIT\run\harqis-work\.env"),
        (r"C:\Users\brian\GIT\harqis-work\.env\storage.json", r"C:\Users\brian\GIT\run\harqis-work\.env"),
        (r"C:\Users\brian\GIT\harqis-work\apps_config.yaml", r"C:\Users\brian\GIT\run\harqis-work"),
    ]
    copy_files_any(files)

    return " ".join(x[0] for x in files)


@SPROUT.task()
@log_result()
def set_desktop_hud_to_back() -> str:
    # Resolve %APPDATA%\Rainmeter\Rainmeter.ini
    rainmeter_ini = Path(os.environ["APPDATA"]) / "Rainmeter" / "Rainmeter.ini"
    set_rainmeter_always_on_top(str(rainmeter_ini))
    _refresh_app()

    return str(rainmeter_ini)


@SPROUT.task()
@log_result()
def run_n8n_sequence() -> str:
    def run_bats_in_sequence(bat_files: list[str]) -> dict:
        """
        Runs each .bat file in the list sequentially.

        Args:
            bat_files (list[str]): List of full paths to .bat files.

        Returns:
            dict: {bat_path: (success: bool, output: str)}
        """
        results: dict[str, tuple[bool, str]] = {}

        for bat_path in bat_files:
            if not os.path.isfile(bat_path):
                msg = "BAT file not found"
                results[bat_path] = (False, msg)
                print(f"\n=== {bat_path} ===")
                print(msg)
                continue

            try:
                # Run the .bat file via cmd.exe
                result = subprocess.run(
                    ["cmd", "/c", bat_path],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )

                success = result.returncode == 0
                output = result.stdout if success else result.stderr

                results[bat_path] = (success, output)

                print(f"\n=== {bat_path} (exit={result.returncode}) ===")
                print(output)

            except Exception as e:
                results[bat_path] = (False, str(e))
                print(f"\nError running {bat_path}: {e}")

        return results

    # Adjust these paths as needed
    bat_list = [
        r"C:\Users\brian\GIT\harqis-work\workflows\n8n\deploy\deploy.bat",
        r"C:\Users\brian\GIT\harqis-work\workflows\n8n\deploy\backup.bat",
        r"C:\Users\brian\GIT\harqis-work\workflows\n8n\deploy\restore.bat",
    ]

    run_bats_in_sequence(bat_list)

    # Simple summary for the task result
    return " | ".join(bat_list)


