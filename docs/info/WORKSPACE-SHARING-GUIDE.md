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
2. Give the recipe a name and recipient label. Review **Details and Filtering**,
   including sources, tags and dates. New standalone recipes start with the last
   30 days; a workspace handoff retains its filters. A name is not a permission
   boundary: inspect the selected content, not just the label.
3. Review **Entries**, **Actions and Ideas**, **Boards**, **Plans**, **Graph**, and
   **Agent**. New recipes include the content types by default; entries are
   required. Exclude anything the audience should not see. Workspace-linked
   objects can remain included independently of entry date filters. Board
   members outside the workspace require per-board opt-in. Completed actions
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
