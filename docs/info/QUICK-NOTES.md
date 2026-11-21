# Quick Notes

Quick Notes holds short-lived checklists independently of actions and ideas.
Open it from the note icon on Kanban, Fleet, or the HUD dashboard, or press **S**
outside an editor. Butler has a Quick Notes tab immediately after Briefings.

## Checklist behavior

- Cards show every item, with pinned cards first. Reorder cards within their pin
  group by dragging the card or its title. Drop in the upper/lower half of another
  card to place it before/after. A drop never changes pin state. Keyboard users
  can focus a card and press Alt+Up/Down; there are no card reorder buttons.
- Select a title to open the note frame. Click a line to edit; Enter adds another
  item in the same card and keeps focus there; click outside the line to save.
  Shift+Enter adds a line break. Text supports bold, italics, bare URLs,
  and Markdown links.
- Drag the item grip vertically to reorder, right to nest beneath the preceding
  parent, or left to return to the top level. Alt+Up/Down and Alt+Left/Right
  on the handle offer keyboard ordering and indentation.
- Nesting has one level. Moving a parent moves its children. Toggling a parent
  toggles its children; individual children can be toggled independently.
- Completed items stay in place with strikethrough. Removing a parent removes
  its children; **Undo removal** restores the removed items.
- Color, pinning, text, ordering, and links autosave. Escape or clickout returns
  from the editor, then closes the dialog. Failed saves retain the draft and
  offer retry. A revision conflict requires explicitly reloading the latest
  note; it never silently overwrites another window's changes.

## Spaces and references

The main page owns the shared Space context; Quick Notes has no context switcher.
New notes are unlinked. Unlinked notes appear in all contexts. Notes linked to
multiple Spaces appear if any linked Space is active. All activity shows all notes.
The note editor's Space picker only changes the note's links.

**Linked actions & ideas** attaches existing records through a searchable,
paginated picker. Attached cards display most recently updated first and open
their existing detail/edit view. Unlinking never deletes the source record.

## Butler and lifecycle

Butler shows sequential full checklist cards, pinned first, with inline editing
and completion toggles. Interaction pauses scrolling. **Resume scrolling**
restarts it; reduced-motion preferences suppress automatic scrolling.

Archive hides notes by default and supports restore. Turn on **Show archived**
to include them after all active notes, with a greyed-out appearance. Pinned
active notes remain first. Dragging cannot cross archive or pin groups. Delete requires
confirmation. Completing all items does not archive a note automatically.

The authenticated `/hfl-corpus/quick-notes` API stores notes per owner in the
configured profile database. Writes use the existing CSRF contract and optimistic
revisions. Creation, archive, and deletion enqueue a lifecycle snapshot in the
same transaction as the note change. Delivery uses the canonical HFL outbox and
stable event deduplication keys. Pending submissions retry when notes are read or
changed. Routine edits and restore do not create corpus entries.

No scheduler, agent execution, new service, package, or environment variable is
required. Notes are scoped to the frontend's configured profile database, like
its shared Space context; independently configured hosts do not share that store.

The [Quick Notes API reference](API-REFERENCE.md#quick-notes-api) documents bodies,
revisions, authentication, and lifecycle effects. Interactive examples and
response schemas are under **Activity · Quick Notes** in the dashboard `/docs`.

The selected checklist opens in a 480px frame over the checklist collection. Click outside or use Close note to save and return. Drag the handle at the left of a row vertically to reorder, right to nest beneath the preceding parent, or left to return to the top level. Alt+Up/Down and Alt+Left/Right on the handle provide keyboard equivalents. Item removal appears on hover/focus. Reference search precedes the two-column linked cards; each card has an unlink icon.
