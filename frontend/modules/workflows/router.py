"""Workflow dashboard and Celery task endpoints."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

import celery_client
from auth import get_current_user
from modules.workflows.service import find_task, refresh_registry
from web import page_context, require_user, templates


router = APIRouter()


@router.get("/workflows", response_class=HTMLResponse)
async def workflows_page(request: Request):
    user, redirect = require_user(request)
    if redirect:
        return redirect
    workflows = refresh_registry()
    default_workflow = "hud" if "hud" in workflows else next(iter(workflows), "")
    task_count = sum(len(workflow.get("tasks", [])) for workflow in workflows.values())
    return templates.TemplateResponse(
        request,
        "modules/workflows/index.html",
        page_context(
            request,
            user,
            "workflows",
            workflows=workflows,
            default_workflow=default_workflow,
            workflow_count=len(workflows),
            task_count=task_count,
        ),
    )


@router.post("/tasks/{workflow}/{task_key}/trigger", response_class=HTMLResponse)
async def trigger_task(request: Request, workflow: str, task_key: str):
    if not get_current_user(request):
        return HTMLResponse(
            '<p class="text-red-400 text-xs">Session expired — please log in again.</p>'
        )

    task = find_task(workflow, task_key)
    if not task:
        return HTMLResponse(
            '<p class="text-red-400 text-xs">Task not found in registry.</p>'
        )

    try:
        task_id = celery_client.dispatch(
            task_path=task["task_path"],
            kwargs=task.get("kwargs", {}),
            queue=task["queue"],
        )
    except Exception as exc:
        return templates.TemplateResponse(
            request,
            "partials/status_panel.html",
            {
                "task_id": None,
                "state": "DISPATCH_ERROR",
                "info": {"note": str(exc)},
                "polling": False,
            },
        )

    return templates.TemplateResponse(
        request,
        "partials/status_panel.html",
        {
            "task_id": task_id,
            "state": "PENDING",
            "info": {"note": "Waiting for a worker to pick up the task…"},
            "polling": True,
        },
    )


@router.get("/tasks/status/{task_id}", response_class=HTMLResponse)
async def task_status(request: Request, task_id: str):
    if not get_current_user(request):
        return HTMLResponse("")

    info = await celery_client.get_task_info(task_id)
    state = info.get("state", "UNKNOWN")
    return templates.TemplateResponse(
        request,
        "partials/status_panel.html",
        {
            "task_id": task_id,
            "state": state,
            "info": info,
            "polling": not celery_client.is_terminal(state),
        },
    )
