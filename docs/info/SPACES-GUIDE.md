# Spaces

Open **Organize → Spaces** to manage a Space's name, color, saved entry filters,
and weekly schedule. The Organize menu contains Spaces, Facets, and Files.

## Create or edit

Choose **New Space**, or search Your Spaces and select one. Set search text or
#tags, activity sources, created/updated/entry date, fixed or rolling dates,
result order, and page size. Save Space applies changes. Unsaved edits prompt
before switching or leaving. Revision checks reject stale updates and removals;
reload to review the latest version rather than overwrite another browser.

From Activity Corpus, Graph, or Kanban, **Space → Manage Spaces** carries the
current filters into this page. Choose New Space or an existing destination,
then Use these filters, review, and Save Space. An existing destination keeps
its name, color, and schedule; the imported filters replace its saved filters.
Multiple selected Spaces require an explicit destination. Their union cannot
be represented by a single filter set: only the additional filters are carried,
and the page calls this out before saving. The handoff uses same-tab session
storage, expires after 30 minutes, is consumed once, and never saves automatically.
Filter text is not placed in the handoff URL or cross-tab local storage.

## Objects and personal context

Entry filters and object assignments are different. Assign actions, ideas, and
boards through their existing activity and board editors. Link Facets to Spaces
from **Organize → Facets** to suggest relevant personal context when sharing.
Neither a link nor a saved filter publishes content.

## Dynamic mode

Add time blocks with weekdays, start, and end. Schedules use the Profile timezone;
an end before the start crosses midnight. Overlaps combine Spaces without
duplicating activity. Gaps show all activity. Enable Dynamic mode in the Space
dropdown; Visualize remains there to inspect the weekly schedule. Its edit action
opens the matching Space here. Manual selection turns Dynamic mode off.

## Preview, sharing, and removal

The shared dropdown keeps Focus on, Dynamic mode, Visualize, Generate share
recipe, and Sharing preview. Sharing preview explains eligible context; a recipe
is a draft until published. Search text is not transferred to a share recipe.
Choose exactly which Facet excerpts a recipient receives. Existing shares retain
their own frozen or live behavior.

Remove Space asks for confirmation. It deletes the saved filter and schedule,
not entries or linked objects. Review object assignments and linked Facets after
removal. Internal workspace APIs and IDs remain compatible; the Facets editor
keeps `/roles` and existing persona/audit storage contracts.
