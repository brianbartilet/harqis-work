"""Discover app integrations, Markdown docs, and pytest files."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

from web import REPO_ROOT


APPS_ROOT = REPO_ROOT / "apps"
POLICY_PATH = Path(__file__).with_name("test_policy.toml")
_APP_KEY = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_-]*$")
_EXCLUDED = {".template", "__pycache__"}


@dataclass(frozen=True)
class AppDocument:
    relative_path: str
    label: str


@dataclass(frozen=True)
class AppTest:
    relative_path: str
    label: str
    safe: bool


@dataclass(frozen=True)
class Application:
    key: str
    label: str
    path: Path
    documents: tuple[AppDocument, ...]
    tests: tuple[AppTest, ...]
    safe_paths: tuple[str, ...]


def _label(key: str) -> str:
    acronyms = {"aaa", "ai", "api", "gpt", "tcg", "mpc", "ynab"}
    return " ".join(
        part.upper() if part.lower() in acronyms else part.title()
        for part in key.replace("-", "_").split("_")
    )


def load_safe_policy() -> dict[str, tuple[str, ...]]:
    if not POLICY_PATH.exists():
        return {}
    try:
        data = tomllib.loads(POLICY_PATH.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    safe = data.get("safe", {})
    return {
        str(app): tuple(str(path).replace("\\", "/") for path in paths)
        for app, paths in safe.items()
        if isinstance(paths, list)
    }


def discover_applications() -> tuple[Application, ...]:
    policy = load_safe_policy()
    applications: list[Application] = []
    if not APPS_ROOT.exists():
        return ()

    for app_dir in sorted(APPS_ROOT.iterdir(), key=lambda path: path.name.lower()):
        if (
            not app_dir.is_dir()
            or app_dir.name.startswith(".")
            or app_dir.name in _EXCLUDED
            or not _APP_KEY.fullmatch(app_dir.name)
        ):
            continue

        docs = sorted(
            (
                AppDocument(
                    relative_path=path.relative_to(app_dir).as_posix(),
                    label=path.relative_to(app_dir).as_posix(),
                )
                for path in app_dir.rglob("*.md")
                if not any(part.startswith(".") or part == "__pycache__" for part in path.relative_to(app_dir).parts)
            ),
            key=lambda doc: (doc.relative_path.lower() != "readme.md", doc.relative_path.lower()),
        )
        configured_safe_paths = policy.get(app_dir.name, ())
        tests = sorted(
            (
                AppTest(
                    relative_path=path.relative_to(REPO_ROOT).as_posix(),
                    label=path.relative_to(app_dir).as_posix(),
                    safe=path.relative_to(REPO_ROOT).as_posix() in configured_safe_paths,
                )
                for path in app_dir.rglob("*.py")
                if path.name.startswith(("test_", "unit_tests"))
                and "__pycache__" not in path.parts
            ),
            key=lambda test: test.label.lower(),
        )
        discovered_test_paths = {test.relative_path for test in tests}
        safe_paths = tuple(
            path for path in configured_safe_paths if path in discovered_test_paths
        )
        applications.append(
            Application(
                key=app_dir.name,
                label=_label(app_dir.name),
                path=app_dir,
                documents=tuple(docs),
                tests=tuple(tests),
                safe_paths=safe_paths,
            )
        )
    return tuple(applications)


def get_application(key: str) -> Application | None:
    if not _APP_KEY.fullmatch(key or ""):
        return None
    return next((app for app in discover_applications() if app.key == key), None)


def resolve_document(app: Application, relative_path: str) -> Path | None:
    candidate = (app.path / relative_path).resolve()
    try:
        candidate.relative_to(app.path.resolve())
    except ValueError:
        return None
    if candidate.suffix.lower() != ".md" or not candidate.is_file():
        return None
    return candidate


def resolve_test(app: Application, relative_path: str) -> str | None:
    normalized = (relative_path or "").replace("\\", "/")
    return normalized if any(test.relative_path == normalized for test in app.tests) else None
