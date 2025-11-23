import os, subprocess
import shutil
from pathlib import Path
from typing import Union, List, Tuple, Dict

from core.apps.sprout.app.celery import SPROUT
from core.apps.es_logging.app.elasticsearch import log_result

from apps.rainmeter.references.helpers.settings import set_rainmeter_always_on_top
from apps.rainmeter.references.helpers.config_builder import _refresh_app

def move_files_any(
    file_map: Union[List[Tuple[str, str]], Dict[str, str]],
    skip_missing: bool = True
):
    """
    Move files where each source has its own destination directory.

    Args:
        file_map:
            - list of (src, dest_dir) tuples, OR
            - dict { src: dest_dir }
        skip_missing (bool):
            Whether to skip missing files (True) or raise an error.

    Returns:
        dict: { "moved": [...], "skipped": [...] }
    """

    # Normalize to list of tuples
    if isinstance(file_map, dict):
        items = [(src, dest) for src, dest in file_map.items()]
    else:
        items = file_map

    moved = []
    skipped = []

    for src, dest_dir in items:
        src_path = Path(src).expanduser().resolve()
        dest_dir_path = Path(dest_dir).expanduser().resolve()

        # Handle missing files
        if not src_path.exists():
            if skip_missing:
                print(f"⚠️ Skipped missing file: {src_path}")
                skipped.append(src_path)
                continue
            else:
                raise FileNotFoundError(f"File not found: {src_path}")

        # Create target directory if needed
        dest_dir_path.mkdir(parents=True, exist_ok=True)
        target = dest_dir_path / src_path.name

        # Move
        try:
            shutil.move(str(src_path), str(target))
            print(f"✅ Moved: {src_path} → {target}")
            moved.append(target)
        except Exception as e:
            print(f"❌ ERROR moving {src_path}: {e}")
            skipped.append(src_path)

    return {"moved": moved, "skipped": skipped}

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
        'C:/Users/brian/GIT/un\harqis-work'
    ]

    git_pull_all(pull_list)

    return "SUCCESS"


@SPROUT.task()
@log_result()
def move_files_targeted() -> str:
    files = [
        (r"C:\Users\brian\GIT\harqis-work\.env", r"C:\Users\brian\GIT\run\harqis-work\.env"),
        (r"C:\Users\brian\GIT\harqis-work\.env", r"C:\Users\brian\GIT\run\\harqis-work\.env"),
        (r"C:\Users\brian\GIT\harqis-work", r"D:\Media\Videos"),
    ]
    move_files_any(files)

    return "SUCCESS"


@SPROUT.task()
@log_result()
def set_desktop_hud_to_back() -> str:
    # Resolve %APPDATA%\Rainmeter\Rainmeter.ini
    rainmeter_ini = Path(os.environ["APPDATA"]) / "Rainmeter" / "Rainmeter.ini"

    # Call your utility
    set_rainmeter_always_on_top(str(rainmeter_ini))

    # Refresh Rainmeter so changes apply
    _refresh_app()

    return "SUCCESS"

