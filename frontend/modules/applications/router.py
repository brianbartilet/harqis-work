"""Routes for application inventory, documentation, and pytest runs."""

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import Response
from modules.hfl_corpus.agent_bridge import owner_auth
from modules.applications import display_settings
from web import static_asset
from fastapi.responses import HTMLResponse
from fastapi.responses import RedirectResponse

from modules.applications.inventory import (
    clear_application_cache,
    discover_applications,
    get_application,
    resolve_document,
    resolve_test,
)
from modules.applications.test_runner import test_runs
from services.markdown import render_markdown
from web import page_context, require_user, templates
from modules.hfl_shares.security import make_csrf_token
from modules.integrations.agents import AGENTS


router = APIRouter(prefix="/applications")


@router.get("", response_class=HTMLResponse)
async def applications_page(request: Request):
    user, redirect = require_user(request)
    if redirect:
        return redirect
    applications = display_settings.decorate(discover_applications())
    return templates.TemplateResponse(
        request,
        "modules/applications/index.html",
        page_context(
            request,
            user,
            "applications",
            applications=applications,
            integration_csrf=make_csrf_token(user),
            latest={app.key: test_runs.latest_for_app(app.key, 1) for app in applications},
        ),
    )


@router.post("/refresh")
async def refresh_applications(request: Request):
    user, redirect = require_user(request)
    if redirect:
        return redirect
    clear_application_cache()
    return RedirectResponse("/applications", status_code=303)


@router.get("/{app_key}", response_class=HTMLResponse)
async def application_detail(request: Request, app_key: str):
    user, redirect = require_user(request)
    if redirect:
        return redirect
    application = get_application(app_key)
    if not application:
        return HTMLResponse("Application not found", status_code=404)
    return templates.TemplateResponse(
        request,
        "modules/applications/detail.html",
        page_context(
            request,
            user,
            "applications",
            application=display_settings.decorate((application,))[0],
            integration_csrf=make_csrf_token(user),
            integration_agents=AGENTS,
            runs=test_runs.latest_for_app(app_key),
        ),
    )


@router.get("/{app_key}/docs/{doc_path:path}", response_class=HTMLResponse)
async def application_document(request: Request, app_key: str, doc_path: str):
    user, redirect = require_user(request)
    if redirect:
        return redirect
    application = get_application(app_key)
    document = resolve_document(application, doc_path) if application else None
    if not application or not document:
        return HTMLResponse("Document not found", status_code=404)
    try:
        rendered = render_markdown(document.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return HTMLResponse("Document could not be read", status_code=422)
    return templates.TemplateResponse(
        request,
        "modules/applications/document.html",
        page_context(
            request,
            user,
            "applications",
            application=display_settings.decorate((application,))[0],
            document_path=document.relative_to(application.path).as_posix(),
            rendered=rendered,
        ),
    )


@router.post("/{app_key}/tests", response_class=HTMLResponse)
async def start_tests(
    request: Request,
    app_key: str,
    mode: str = Form(...),
    test_path: str = Form(""),
):
    user, redirect = require_user(request)
    if redirect:
        return redirect
    application = get_application(app_key)
    if not application:
        return HTMLResponse("Application not found", status_code=404)

    if mode == "safe":
        targets = list(application.safe_paths)
    elif mode == "full":
        targets = [f"apps/{application.key}"]
    elif mode == "file":
        resolved = resolve_test(application, test_path)
        targets = [resolved] if resolved else []
    else:
        targets = []
    if not targets:
        return HTMLResponse(
            '<div class="rounded-lg bg-amber-950/40 p-3 text-xs text-amber-300">No permitted tests matched this request.</div>',
            status_code=400,
        )

    run = test_runs.start(application.key, mode, targets)
    return templates.TemplateResponse(
        request,
        "modules/applications/test_run.html",
        {"run": run},
    )


@router.get("/test-runs/{run_id}", response_class=HTMLResponse)
async def test_run_status(request: Request, run_id: str):
    user, redirect = require_user(request)
    if redirect:
        return redirect
    run = test_runs.get(run_id)
    if not run:
        return HTMLResponse("Test run not found", status_code=404)
    return templates.TemplateResponse(
        request,
        "modules/applications/test_run.html",
        {"run": run},
    )


@router.post("/test-runs/{run_id}/cancel")
async def cancel_test_run(request: Request, run_id: str):
    user, redirect = require_user(request)
    if redirect:
        return redirect
    await test_runs.cancel(run_id)
    run = test_runs.get(run_id)
    if not run:
        return HTMLResponse("Test run not found", status_code=404)
    return templates.TemplateResponse(
        request,
        "modules/applications/test_run.html",
        {"run": run},
    )


def display_payload(application):
    shown = display_settings.decorate((application,))[0]
    return {'display_name': shown.label, 'icon_url': ('/applications/'+application.key+'/icon?v='+shown.icon_version) if shown.icon_version else static_asset('img/connectors/application.svg')}


@router.get('/{app_key}/icon', dependencies=[Depends(owner_auth)])
def application_icon(app_key: str):
    if not get_application(app_key):
        raise HTTPException(404, 'Application not found.')
    data = display_settings.icon(app_key)
    if not data:
        return RedirectResponse(static_asset('img/connectors/application.svg'), status_code=307)
    return Response(data, media_type='image/webp', headers={'Cache-Control': 'private, no-cache', 'X-Content-Type-Options': 'nosniff'})


@router.post('/{app_key}/settings', dependencies=[Depends(owner_auth)])
async def save_application_settings(request: Request, app_key: str):
    application = get_application(app_key)
    if not application:
        raise HTTPException(404, 'Application not found.')
    form = await request.form()
    upload = form.get('icon')
    try:
        image = None
        if upload and getattr(upload, 'filename', ''):
            image = display_settings.normalize_image(await upload.read(display_settings.MAX_IMAGE_BYTES + 1))
        name = form.get('display_name')
        if not isinstance(name, str):
            raise ValueError('Enter a display name.')
        display_settings.save(app_key, name, image)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    finally:
        if upload and hasattr(upload, 'close'):
            await upload.close()
    return display_payload(application)


@router.post('/{app_key}/settings/reset', dependencies=[Depends(owner_auth)])
def reset_application_settings(app_key: str):
    application = get_application(app_key)
    if not application:
        raise HTTPException(404, 'Application not found.')
    display_settings.reset(app_key)
    return display_payload(application)
