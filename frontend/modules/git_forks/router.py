"""Authenticated fork fleet report and guarded operation routes."""

from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse

from apps.git.fleet import (
    FleetError,
    cherry_pick_to_worktree,
    deploy_fork,
    load_latest_report,
    run_fork_tests,
    scan_fleet,
)
from web import page_context, require_user, templates


router = APIRouter(prefix="/git-forks")


def _operation_response(request: Request, result: dict, *, status_code: int = 200):
    return templates.TemplateResponse(
        request, "modules/git_forks/operation.html", {"result": result}, status_code=status_code,
    )


@router.get("", response_class=HTMLResponse)
async def git_forks_page(request: Request):
    user, redirect = require_user(request)
    if redirect:
        return redirect
    return templates.TemplateResponse(
        request,
        "modules/git_forks/index.html",
        page_context(request, user, "git_forks", report=load_latest_report()),
    )


@router.post("/scan", response_class=HTMLResponse)
async def scan_git_forks(request: Request, write_hfl: bool = Form(False)):
    user, redirect = require_user(request)
    if redirect:
        return redirect
    try:
        report = scan_fleet()
        if write_hfl:
            from workflows.git_forks.hfl import persist_scan_entries

            report["hfl"] = persist_scan_entries(report)
        return _operation_response(request, {"status": "scan-complete", "report": report})
    except (FleetError, OSError) as exc:
        return _operation_response(request, {"status": "error", "error": str(exc)}, status_code=422)

@router.post("/sync", response_class=HTMLResponse)
async def sync_git_fork(
    request: Request,
    repository: str = Form(...),
    branch: str = Form(...),
    commits: str = Form(...),
    test_paths: str = Form(""),
    publish_pr: bool = Form(False),
    pr_title: str = Form(""),
    pr_body: str = Form(""),
):
    user, redirect = require_user(request)
    if redirect:
        return redirect
    try:
        result = cherry_pick_to_worktree(
            repository, [value for value in commits.split() if value], branch=branch,
            test_paths=[value for value in test_paths.splitlines() if value.strip()],
            publish_pr=publish_pr, pr_title=pr_title, pr_body=pr_body,
        )
        return _operation_response(request, result)
    except (FleetError, OSError, ValueError) as exc:
        return _operation_response(request, {"status": "error", "error": str(exc)}, status_code=422)


@router.post("/test", response_class=HTMLResponse)
async def test_git_fork(
    request: Request,
    repository: str = Form(...),
    branch: str = Form("main"),
    test_paths: str = Form(""),
):
    user, redirect = require_user(request)
    if redirect:
        return redirect
    try:
        result = run_fork_tests(
            repository, branch=branch,
            test_paths=[value for value in test_paths.splitlines() if value.strip()],
        )
        return _operation_response(request, result)
    except (FleetError, OSError, ValueError) as exc:
        return _operation_response(request, {"status": "error", "error": str(exc)}, status_code=422)


@router.post("/deploy", response_class=HTMLResponse)
async def deploy_git_fork(
    request: Request,
    repository: str = Form(...),
    branch: str = Form(...),
    role: str = Form("host"),
):
    user, redirect = require_user(request)
    if redirect:
        return redirect
    try:
        return _operation_response(request, deploy_fork(repository, branch=branch, role=role))
    except (FleetError, OSError, ValueError) as exc:
        return _operation_response(request, {"status": "error", "error": str(exc)}, status_code=422)
