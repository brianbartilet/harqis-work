# Facets, Soul, and Spaces

Facets describe aspects of the owner’s life. Spaces collect activity and objects.
The **Organize → Facets** page supports name, color, Markdown Soul, PDF/DOCX/
Markdown/text/image attachments, Space associations, entity links, private agent
observations, archive/restore, and revision history. Internal `workspace` IDs,
routes, query parameters, and database names remain compatible.

## Sharing

Open a share recipe and expand **Personal context · Facets and Soul**. Space links
suggest relevant facets; they do not grant access. Select individual Soul heading
sections, attachment excerpts, or owner-approved journal observations. Review the
exact text in the Agent tab before generating a share. Attachment excerpts are split
into bounded chunks; selecting an excerpt does not enable its original download.
The separate original-download checkbox grants access to the **entire file**.

Selected personal context is available to the share agent, without a recipient-facing
About page or excerpt catalogue. The agent uses the published personal context in its answers without exposing
excerpt links or popups. Activity citations still open their shared sources. Private journal evidence paths, unselected sections, and role metadata
are excluded. Company, role, job description, audience, tone, and optional
icebreaker guidance influence presentation; they are not evidence of qualifications.
Treat all guidance as potentially visible through answers.

Published persona content is frozen, including in live activity shares. To refresh,
edit the saved recipe, select the current role revision, inspect the preview, and
use the existing share’s **Update from recipe** operation or generate a new share.
Previously selected revisions are identified in the form. Remove selections and
update the share, or revoke the share, to withdraw access. Archiving a role stops
new selection and analysis but does not erase prior publications or downloads.
Detached files remain immutable for previously approved references and history.

## Attachments

Facets allow 20 attachments, at most 20 MB each, with 10 files per upload. Extraction
is private and reports success/failure. Text is capped at 60,000 characters; PDFs
process at most 50 pages. DOCX paragraphs and tables are supported. PDF encryption
and empty extraction produce errors; upload scanned PDF pages as images for OCR.
Images require Tesseract installed on the frontend host, plus `pytesseract` and
Pillow; images are limited to 25 megapixels and OCR has a 45-second timeout.
Install Python dependencies from the root requirements. No extraction error falls
back to silently publishing a file. Review OCR accuracy before sharing.

## Persona audit

**Runtime:** Celery; **schedule owner:** Celery Beat. A bounded Anthropic transform
uses `workflows/hfl/prompts/persona_audit.md`; no autonomous tool-selection loop.
The registered task is `workflows.hfl.tasks.persona_audit.persona_audit`.
Its active weekly schedule is Sunday 09:00 Asia/Singapore, on `WorkflowQueue.HOST`.
Manual **Analyze now** dispatches the same task with a unique run ID.
`HFL_PERSONA_AUDIT_DAY`, `HFL_PERSONA_AUDIT_HOUR`, and
`HFL_PERSONA_AUDIT_MINUTE` optionally override the weekly timing (Singapore time).

The owner frontend stores roles with its profile database and exposes bearer-
authenticated `/api/hfl/roles` and `/api/hfl/roles/audit/run`. Set
`HFL_PERSONA_API_URL` on the worker to this **same frontend**, especially if its
profile/Spaces live on a different host from the corpus. It defaults to
`HFL_CORPUS_API_URL`. `HFL_CORPUS_API_TOKEN` authenticates the call. The manual
dispatch queue can be overridden with `HFL_PERSONA_QUEUE`; it defaults to HOST.
Use one owning frontend, not independent role copies on multiple hosts.

Analysis uses non-secret evidence from linked Spaces: recent 90-day entries plus
linked actions/ideas. Deleted Spaces fail closed. Content hashes identify new or
changed evidence. Each role is limited to 100 sources / 60,000 characters per run,
with 6,000 characters per source and at most 12 observations. Deferred counts and
coverage limits appear in the run history. Model results must cite supplied IDs.
Prior persona/audit/radar outputs are excluded as new evidence.

Observations are appended as **pending** and never overwrite Soul. Approve/reject
them in the journal. Approval makes a note selectable; sharing still requires an
explicit recipe selection. Concurrent owner edits stop stale results, and an
interprocess lock serializes runs. Failed runs preserve already completed role
work and retry safely using the same run ID and evidence checkpoints.

Every logical run submits a concise HFL entry with source **persona-audit** and
the `secrets` tag, including no-change and failed runs. Stable delivery IDs prevent
duplicates; retried runs replace their receipt. Raw attachments and full personal
narratives are excluded from these reports. The standard HFL outbox preserves
delivery; pending reports are retried on subsequent runs. Forwarded receipts are
shown as **HFL queued** until the canonical HFL worker consumes them; a running
preview analysis worker does not replace that canonical persistence worker. If the owner API itself
is unreachable, Celery retries twice; no owner-side report can be written until
that API is reachable. Task logs identify this delivery failure.

No new credentials are needed. Existing `ANTHROPIC` configuration is used. Restart
the owning frontend, worker, and Beat after deployment; regenerate the local task
registry. A local review instance does not activate Beat or production workers.

## Local review

Run from the repository virtual environment:

```powershell
.venv/Scripts/python.exe scripts/persona_preview.py frontend
.venv/Scripts/python.exe scripts/persona_preview.py worker
```

Visit `http://127.0.0.1:8093/roles` and sign in with the existing local credentials.
The preview copies the local profile database once into
`.harqis-data/persona-preview`, uses separate share/intent stores and the
`persona-preview.host` queue, and reads configured corpus evidence. Manual audits
still produce the requested real `persona-audit` HFL entries. It does not run Beat.

## Validation

`frontend/tests/test_roles.py` covers owner authentication/CSRF, sanitized Markdown,
revision conflicts, private observations, frozen excerpts, citation stability,
incremental analysis, and report failure handling. Existing sharing, Space, and
guest-view regression tests protect compatibility.

### Facet editor patterns

Facet colors use the pinned-date palette (existing custom colors remain selectable). Linked Spaces use a checkbox dropdown. Related entities follow Linked Spaces in a vertical layout; the type/search picker returns at most 50 results and preserves selections across filters. Soul renders sanitized Markdown on blur and opens for editing with a click, Enter, or Space. Save always uses the underlying Markdown. The frontend pattern review skill is integrated into feature clarification to inspect existing controls before implementing new UI.

The Facets page follows the recipe layout: a wide editor on the left and the facets list with analysis controls in the right sidebar. At 900px and below, the facets sidebar appears first, above the editor.

The sidebar shows facets in two columns and an archived toggle. Analysis help precedes the centered Analyze now button, with queued/error feedback inside the same section. Dropdowns use the recipe SVG caret; selected entities use typed cards with Remove controls.

### Spaces management

Use **Organize → Spaces** to create, edit, or remove saved Spaces. The dropdowns
on Corpus, Graph, and Kanban keep selection, Dynamic mode, Visualize, and sharing.
Manage Spaces carries filters into an explicit save flow. See [Spaces guide](SPACES-GUIDE.md).
Facets is the visible name for the former Roles feature; `/roles`, API paths,
identifiers, and stored records are unchanged.

The info icon beside **Your facets** opens an in-page guide with examples, Soul
writing tips, Space links, journal review, sharing controls, and archive behavior.
It uses the same accessible help-dialog presentation as Spaces.

### How agents and shares use Facets

The analysis agent works for the owner: manual and weekly runs check active
facets with linked Spaces, compare new or changed evidence, and propose private,
evidence-linked journal observations. It uses the facet name and Soul alongside
recent entries and linked actions/ideas. Review suggestions before approving
anything. Approval only makes an observation available to select in a recipe;
it does not publish it or edit the Soul. Analysis history reports coverage and
outcomes, and each run records an HFL receipt with source `persona-audit`.

The share chat agent works within the recipient's published context. Select
Soul sections, extracted attachment excerpts, and approved observations in
**Personal context · Facets and Soul**. Linked Spaces provide suggestions, not
automatic selections. Optional opportunity and audience guidance helps shape
answers; it is not evidence of qualifications and may be reflected in answers.

Review selected excerpts in **Agent → Personal context** and test the agent before publishing. These
excerpts inform the agent's answers without appearing as a separate recipient view. The chat uses them alongside the included activity, is instructed
to cite evidence and acknowledge insufficient context, and cannot browse the
private Facet library or edit the owner's records. Original-file downloads
require separate selection.

Recipes retain selected personal revisions. Later Facet edits and approvals do
not silently update that context, including in live-activity shares. Select the
updated excerpts in the recipe and explicitly update or generate the intended
share. Archiving a Facet does not revoke existing shares.
