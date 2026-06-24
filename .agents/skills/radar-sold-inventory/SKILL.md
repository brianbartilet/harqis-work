---
name: radar-sold-inventory
description: >
  Run the sold-inventory radar that cross-references sold TCG Marketplace orders
user-invocable: true
allowed-tools: Bash Read Glob Grep Edit Write
---

Run the sold-inventory radar that cross-references sold TCG Marketplace orders
against the current EchoMTG inventory and active TCG listings. It is the
automated replacement for the manual monthly "review completed/cancelled orders →
remove sold cards in EchoMTG" process. See
`workflows/purchases/tasks/sold_inventory_radar.py` and `workflows/purchases/README.md`.

This is a **two-phase, operator-approved** flow:
1. **SCAN** → write a CSV review list to `results/` (no changes).
2. You **edit the CSV**: set `approved` to `yes` on the rows you want actioned, save it.
3. **APPLY** → act ONLY on the approved rows (mark sold + remove inventory + delist).

⚠️ Apply is **destructive**. It runs only against rows you explicitly approved in
the CSV, and only after you confirm.

> Before any Python here, bootstrap the env (load `.env/apps.env` + machine env_vars)
> per the `harqis-env-context` skill, or `${PLACEHOLDER}` creds won't resolve and TCG
> MP login fails with `KeyError: 'accessToken'`.

## Arguments

`$ARGUMENTS` (all optional):

| Token | Meaning |
|---|---|
| `--approved <csv>` | Go straight to the APPLY phase using this approved CSV (filename resolved under `results/`). |
| `--days N` | Live-poll window for terminal orders (default 60). |
| `--limit N` | Cap inventory items scanned (useful for a quick scan). |
| `--source hybrid\|live\|es` | Order history source (default `hybrid`). |
| `--orphan-mode off\|corroborated\|all` | Treat notes whose mapped listing is no longer active (`listing_gone`): `corroborated` (default, HIGH only) / `all` (also LOW orphans) / `off`. Forward as `orphan_mode=`. |

If `--approved` is given, skip to Step 4. Otherwise run the SCAN (Steps 1–3).

## Steps

1. **Confirm config.** Needs live `TCG_MP`, `ECHO_MTG`, `ECHO_MTG_FE` in
   `apps_config.yaml` with creds in `.env/apps.env`. Bootstrap the env first
   (see `harqis-env-context`). A `KeyError: 'accessToken'` / `401` means the env
   wasn't loaded or the creds are missing — report and stop.

2. **SCAN (no changes).** Run a dry run, forwarding the parsed args:
   ```bash
   python -c "from workflows.purchases.tasks.sold_inventory_radar import radar_sold_inventory; \
     print(radar_sold_inventory(dry_run=True, last_x_days=<DAYS>, limit=<LIMIT_OR_None>, source='<SOURCE>'))"
   ```
   This writes `results/sold_inventory_radar-<ts>.csv` — one row per card, **sorted
   by listing price (desc)**, with the lead columns `approved, card_name,
   listing_price, assessment, confidence, sold_in_orders` followed by the full
   EchoMTG + TCG MP detail and join keys. The `approved` column is `no` on every row.
   Summarise: candidate count, by confidence tier, the priciest/notable cards and
   the orders they sold in (quote the `assessment`). Flag ambiguous rows
   (medium-confidence, cancelled-order matches) for physical verification.

3. **Hand the CSV to the operator for approval.** Tell them explicitly:
   > Open `results/sold_inventory_radar-<ts>.csv`, set **`approved` = `yes`** on the
   > rows you want actioned, save it (same name or a new one under `results/`), and
   > tell me the filename.
   Then **stop and wait** — do not apply anything yet. Accept `yes/y/true/1/x` as approval.

4. **APPLY the approved rows.** Once the operator gives the approved CSV filename
   (in `results/`), first preview, then act:
   ```bash
   # preview — counts only, no API calls
   python -c "from workflows.purchases.tasks.sold_inventory_radar import apply_radar_approvals; \
     print(apply_radar_approvals('<approved_csv>', dry_run=True))"
   ```
   Report how many rows are approved, confirm with the operator, then run for real:
   ```bash
   python -c "from workflows.purchases.tasks.sold_inventory_radar import apply_radar_approvals; \
     print(apply_radar_approvals('<approved_csv>', dry_run=False))"
   ```
   For each approved row this marks the card sold in EchoMTG earnings, removes the
   inventory item, and delists it on TCG MP — using the ids stored in the row.
   Narrow with `apply_actions=(...)` if the operator only wants some of the three.

5. **Report.** Print the apply summary and the audit CSV path
   (`results/sold_inventory_radar-applied-<ts>.csv`, with per-row `action_results`),
   and remind the operator to physically verify before re-listing.

## Notes

- Two **detections** (see the `detection` column):
  - `sold_still_listed` — still listed AND sold. high = exact listing match, medium =
    product+foil. Action: mark sold + remove + **delist**.
  - `listing_gone` — the note's mapped `tcg_mp_listing_id` is no longer active (the
    listed copy sold or the listing was removed). high = a sold order corroborates;
    low = none found (verify). Action: mark sold + remove (**no delist** — already gone).
- In practice TCG order details expose product_id but not listing_id, so
  `sold_still_listed` matches are mostly **medium** — verify multiples by hand. The
  strongest "definitely sold" signal is `listing_gone` + HIGH.
- `--orphan-mode` defaults to `corroborated` (HIGH orphans only). Use `all` to also
  surface uncorroborated dead-listing items (LOW). Orphan detection is auto-skipped
  if TCG MP returns zero active listings (listings likely globally disabled).
- Apply skips delist for `listing_gone` rows automatically (no live listing to remove).
- **Multi-copy cards:** a TCG listing maps to ALL EchoMTG copies of a card, so apply
  does NOT blindly delist `sold_still_listed` rows — it sets the listing quantity to
  the EchoMTG copies that REMAIN after removal (delists only at 0). The CSV's
  `echo_owned_count` shows how many you hold; approve one row per copy actually sold.
  Pass `reconcile_quantity=False` to force a blunt delist instead.
- APPLY acts purely from the approved CSV (not a fresh scan), so what you approve is
  exactly what runs. The audit CSV records the result of each action.
- Depends on `generate_tcg_mappings` notes + `generate_audit_for_tcg_orders` (now
  tracking Cancelled/Not Received) for the ES feed; the live poll covers gaps.
