# Share a workspace with a QR code

Use **Express > Share Activity** to publish a reviewed, read-only guest view of
workspace content. Guests get the content you approve, not access to your owner
workspace, VPN, or editing tools. A QR code encodes the same access link you can
copy and send; treat both as access credentials.

For implementation and administration, see [Activity Corpus Sharing](HFL-CORPUS-SHARING.md).

## Generate and review a share

1. Select the intended workspace context in Corpus, Activity Graph, or Kanban,
   then choose **Generate share recipe**. This opens an unsaved sharing draft
   with eligible context preselected. Alternatively open **Express > Share
   Activity** (`/sharing`) to build a recipe yourself.
2. Give the recipe a name and recipient label. Review **Settings**,
   including sources, tags and dates. New standalone recipes start without a date
   restriction and require source selection; a workspace handoff retains its filters. A name is not a permission
   boundary: inspect the selected content, not just the label.
3. Review **Entries**, **Actions**, **Boards**, **Plans**, **Graph**, and
   **Agent**. New recipes include the content types by default; entries are
   required. Exclude anything the audience should not see. Workspace-linked
   objects can remain included independently of entry date filters. Board
   members outside the workspace require per-board opt-in for ordinary recipes;
   personalized recipes include eligible members of linked boards. Completed actions
   and dismissed ideas are excluded by default.
4. Expand **Access, expiry, and reference controls**. Choose the access mode
   (QR, PIN, email OTP, or manual approval), expiry, concurrent-session cap and
   maximum redemptions. Check references individually. Leave **Include secrets**
   off unless deliberately required; enabling it requires the corpus secrets PIN.
5. Choose whether to **Freeze generated shares at creation**. Keep it checked
   for a reviewed snapshot. Uncheck it for live updates, then review the
   per-content-type automatic inclusion policies before publishing.
6. Review the preview and warnings, including entries, object details and
   reference permissions. **Save recipe** if you want a reusable recipe and
   later in-place updates from it. Saving is not publishing.
7. Select **Generate snapshot and QR**, confirm the recipient-visible share
   name, then **Generate share**. The handoff shows the QR code and copyable
   link. In PIN mode, save the displayed PIN securely: it is shown only once.
8. Send the QR/link only to the intended audience and provide any required
   access instructions. In **Generated shares**, **Preview** lets the owner
   inspect the published view; **QR + link** reopens the handoff for an active
   share with a retained link, but does not reveal its PIN again.

Guests begin in chat with an Activity entries sidebar. The menu offers Actions
and ideas, Plans, Idea boards and Activity graph only when enabled and populated
in the published snapshot. These are read-only; graph exploration does not edit
the source workspace or replace the published layout.

## What the access limits mean

| Control | What it limits | What it does not mean |
|---|---|---|
| **Maximum redemptions** | Successful new sessions for this share in each cookie-identified browser. Default **5**; **0** means unlimited; maximum **1000**. | Not five people, five total scans, or a global share quota. |
| **Concurrent sessions** | Active sessions at the same time, subject to the server's configured ceiling. | Not a lifetime redemption allowance. |
| **Allow only the first successful session** | One successful session for the share; overrides Maximum redemptions. | Not one session per browser. |
| **Expires at** / **No expiry** | The lifetime of the share grant. | No expiry does not make individual browser sessions permanent. |

Rescanning in a browser with an active session resumes that session without
spending another redemption. Failed attempts do not spend one either. **Close
session** or session expiry releases a concurrent slot, but does not reset that
browser's redemption count. A new successful session spends another redemption.
Sessions have a fixed duration shown by the interface, rather than being extended
indefinitely by activity.

For example, with Maximum redemptions set to 5 and one concurrent session, a
browser can start up to five sessions over time, but only one session can be
active at once. Closing the first frees the slot; starting the next consumes the
second redemption. Increasing the allowance to 10 would permit ten new sessions
per browser, not ten concurrent users.

The browser allowance is cookie-based, not verified identity. Clearing cookies,
using a different browser/profile, or expiration of the browser-identity cookie
starts a separate allowance. Do not rely on this limit alone to identify people.
Use the appropriate access mode and revoke a link that should no longer be used.

### Instant QR is a different handoff

The saved-recipe instant QR action creates a throwaway share: QR access, one-day
expiry, one concurrent session and only the first successful session. It enables
reference sharing subject to the recipe's reference exclusions. It is not added
to **Generated shares**. Use normal **Generate snapshot and QR** when you need a
managed share with the access settings you selected and a reopenable handoff.

<a id="personalize-a-share-with-one-entity"></a>
### Personalize a share with multiple entities

1. Expand **Share with** above **Saved recipes**. This accordion has its own
   controls and leaves your current recipe untouched until you choose **Review**.
2. Defaults are **People**, **All sources for this entity** on, **Save as a
   reusable entity template** off, and the workspace named **Default** selected.
   If there is no unique Default workspace, choose a workspace or explicitly
   choose **No workspace context**. References start off and content is frozen.
3. Search and add entity cards. Cards show the name, entity-type pill and entry
   count. Selections persist across searches and type changes, so people,
   companies, topics and other types can be combined. Remove individual cards or
   use **Clear all**. Activity matching **any** selection is included once, with
   one shared set of filters and workspace selections.
   **Recipient** starts with the first selected name and stays editable. Adding
   or removing entities preserves it; Clear all resets it. This is still a share
   for one individual, who can see the entire combined scope.
4. Open the **Add workspace context** dropdown to select one or more workspaces.
   Workspace objects and supporting entries can be included even when they do not
   mention any selected entity.
5. Choose **Review** to load an unsaved recipe into the normal editor. The
   first selection supplies the initial **Recipient**, which you can edit. Review Entries, Actions, Boards,
   Plans, Graph and Agent as usual. All-people selections start with the **People**
   graph preset; mixed types use **Timeline**. Refine filters, exclude objects and check inclusion reasons.
6. To reuse the rules later, enable **Save as a reusable entity template** before
   Review, refine the recipe, and choose **Save recipe**. Saving clears all selected entities
   and recipient while keeping filters and exclusions. Load that saved template,
   open Share with and choose the next entities; its saved rules remain in effect.
7. For an immediate, disposable QR, use **Instant Share** inside the accordion.
   It uses the accordion's selections, independently of subsequent main-editor
   changes. Use **Generate snapshot and QR** in the editor for a managed share
   that includes your detailed edits.

The accordion's Instant QR can be redeemed once within **24 hours of creation**.
The first successful redemption starts a **full 24-hour session** on that browser,
including when the QR is scanned near its redemption deadline. Revisiting resumes
that session without extending it. A second browser cannot redeem it; revocation
or session expiry ends access. For example, a QR created Monday at 10:00 and
redeemed Tuesday at 09:00 gives access until Wednesday at 09:00. An unredeemed QR
expires Tuesday at 10:00. Other Instant Share paths retain their existing timing.
Instant shares are not listed under Generated shares and cannot be reopened there.

Errors appear in the accordion and preserve its choices and the main draft.

Selecting Alex does not authenticate Alex. QR possession still grants access in
QR mode. Full records remain intact and can mention other people; hiding a graph
node does not redact names or attachment contents. Missing extraction can omit
relevant activity. A merged or removed entity must be selected again; lookup
failure never falls back to an unrestricted share.

Generated shares keep all their selected entities independently of the template.
**Update from saved recipe** preserves the share's bound entities while applying
the saved rules. Live shares use their captured binding and inclusion policies;
new relationships can change their scope, so keep snapshots frozen when review
must cover exactly what is published.

See [personalization implementation and boundaries](HFL-CORPUS-SHARING.md#personalized-recipes)
for the exact relationship rules and validation coverage.

## Expiry, refresh and deletion

| Action or event | Content and access behavior |
|---|---|
| Save or edit a recipe | Changes reusable instructions only. Existing generated shares are not automatically republished. |
| Frozen share | Keeps its generation-time content unless the owner explicitly updates it from a saved recipe. |
| Live share | Refreshes content on access, subject to the configured refresh interval, using the recipe copy captured by the share and its inclusion policies. It does not automatically adopt later saved-recipe edits. |
| **Update from saved recipe** | Explicitly republishes an active share from its latest saved recipe. Save edits first. Preserves the share name, QR/link, expiry, access settings, frozen/live policy, sessions and existing reference permissions. It can also replace the captured live configuration. |
| Grant expiry | Blocks the share and invalidates its guest sessions; browsing or refreshing content does not extend the grant. |
| **Revoke now** | Immediately invalidates guest access, including active sessions. |
| **Delete** on an inactive share | Removes the expired/revoked share. Revoke an active share first; the UI offers Delete once it is inactive. |
| Delete a saved recipe | Does not delete or revoke its generated shares. Those shares can no longer use Update from saved recipe if their recipe is gone. |

Live recipes can update approved objects or automatically include newly matching
objects, independently for entries, actions, ideas and boards. Explicit exclusions
remain excluded and new references stay disabled. Relative **From days** windows
roll forward for live shares; frozen snapshots retain their resolved dates.
If a live refresh fails, the guest can see the last successfully shared snapshot
with a refresh warning. Do not interpret that as a successful content update.

Updating content is not renewing access: it does not reset redemptions or extend
expiry. To change a generated share's authentication, access limits or expiry,
generate a new share with the desired settings and revoke the old one if needed.
Distribute the new QR/link. An expired or revoked share cannot be revived using
Update from saved recipe.

## `work-portfolio` versus `linkedin-share`

These are owner-defined context names, not built-in share modes or security
presets. The application does not assign different expiry, redemption limits,
authentication or content permissions merely because a context has either name.
There is no automatic LinkedIn publication implied by `linkedin-share`.

Treat each as a separately curated audience/context. Before sharing either one,
compare its actual workspace scope, included entries and objects, references,
secret-content switch, access settings and frozen/live policy in the recipe and
preview. Do not assume that one is broader, safer or contains the same projects
as the other. Their actual content differences depend on the owner's saved
selections and are intentionally not reproduced in this public guide.

If you intend `work-portfolio` for a detailed work review and `linkedin-share`
for a narrower external handoff, configure and preview those differences
explicitly. That is an example audience policy, not an enforced product rule.
The default five-redemption allowance is the same regardless of either name;
a saved override is a recipe/share setting, not a special context behavior.

## Troubleshooting

- **All redemptions used:** a new session is blocked for that browser/share.
  Resuming a still-active session does not consume another redemption. Ask the
  owner for a replacement share if more access is intended.
- **No concurrent slot available:** another session may still be active. Close
  that guest session or wait for its expiry; increasing the redemption allowance
  does not create concurrent slots.
- **QR + link unavailable:** the share may be expired/revoked, or an older share
  may not have a retained link. Generate a new share when necessary.
- **Recipe edits are missing for guests:** save the edits, then explicitly use
  Update from saved recipe, or generate a new share. Page reload alone does not
  publish saved-recipe changes.
- **Update unavailable:** verify that the share is active and its saved recipe
  still exists. Empty or oversized replacement content is rejected without
  replacing the share.

Related: [frontend workspace sharing](../../frontend/README.md#workspace-context-sharing)
and [sharing lifecycle and operations](HFL-CORPUS-SHARING.md#lifecycle).

## Organizing the source context

Use **Organize → Spaces** to manage saved entry filters, colors, and weekly schedules.
The Space dropdown on Corpus, Graph, and Kanban retains selection, Dynamic mode,
Visualize, and sharing actions. **Manage Spaces** carries filters to the dedicated
editor for an explicit save. See [Spaces guide](SPACES-GUIDE.md).
Personal context is managed in **Organize → Facets**, formerly Roles; publishing
still requires explicit selection of the recipient’s allowed excerpts.

The info icon beside **New recipe** / **Edit recipe** opens the detailed in-page
recipe guide. Facet selection cards and Markdown share context are in the **Agent** tab,
under **Personal context · Facets and Soul**; they remain part of the same recipe
form and are preserved when switching tabs.

Share context is one Markdown field for the purpose, audience, background, and
conversation style. Use its info icon for adaptable examples. Existing structured
guidance loads as Markdown headings; saving preserves it in the new field.
Guidance is distinct from evidence and cannot expand the shared scope.

In the **Agent** tab, Agent guide supplies optional agent instructions.
**Suggested questions** supports Automatic (shared-context prompts), Custom (up to
five questions, one per line), or Off. Choices are saved with the recipe and
published snapshot; update an existing share explicitly to apply recipe changes.
