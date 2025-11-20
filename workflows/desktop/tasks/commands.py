import os, subprocess
from core.apps.sprout.app.celery import SPROUT


@SPROUT.task()
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

