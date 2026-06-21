---
name: radar-sold-inventory
description: >
  Run the TCG sold-inventory radar — find EchoMTG cards already sold on The TCG
  Marketplace (across Completed/Picked Up/Cancelled/Not Received orders) that are
  still in the inventory AND still actively listed, the state that produces orders
  you can't fulfil. Previews the candidates first (dry run), then optionally marks
  them sold in EchoMTG earnings, removes them from inventory, and delists them on
  TCG MP — always writing a per-card CSV review list (both EchoMTG + TCG MP fields)
  to harqis-work/results/ and to ES. Wraps
  workflows.purchases.tasks.sold_inventory_radar.radar_sold_inventory.
  Trigger phrases (non-exhaustive): "sold inventory radar", "find sold but still
  listed", "clean up sold cards", "echomtg cards i already sold", "tcg unfulfillable
  listings", "remove sold cards from inventory".
---

Run the sold-inventory radar that cross-references sold TCG Marketplace orders
against the current EchoMTG inventory and active TCG listings. It is the
automated replacement for the manual monthly "review completed/cancelled orders →
remove sold cards in EchoMTG" process. See
`workflows/purchases/tasks/sold_inventory_radar.py` and `workflows/purchases/README.md`.

⚠️ The underlying task is **destructive by default** (marks sold + removes
inventory + delists). This skill always **previews first** and only applies after
the operator confirms.

## Arguments

`$ARGUMENTS` (all optional):

| Token | Meaning |
|---|---|
| `--apply` | Skip straight to applying (still prints the list). Without it, preview only. |
| `--days N` | Live-poll window for terminal orders (default 60). |
| `--limit N` | Cap inventory items scanned (useful for a quick look). |
| `--min-confidence high\|medium\|low` | Only act on matches at/above this tier (default `low`). `high` = exact listing match only. |
| `--source hybrid\|live\|es` | Order history source (default `hybrid`). |

## Steps

1. **Confirm config.** The task needs live `TCG_MP`, `ECHO_MTG`, and `ECHO_MTG_FE`
   sections in `apps_config.yaml` with credentials in `.env/apps.env`. If a call
   returns `401`/auth errors, report it as a config gap and stop.

2. **Preview (always first).** Run a dry run, forwarding the parsed args:
   ```bash
   python -c "from workflows.purchases.tasks.sold_inventory_radar import radar_sold_inventory; \
     print(radar_sold_inventory(dry_run=True, last_x_days=<DAYS>, limit=<LIMIT_OR_None>, \
     source='<SOURCE>', min_confidence='<CONF>'))"
   ```
   Read the generated CSV (`results/sold_inventory_radar-<ts>.csv`) — one row per
   card with both the EchoMTG side (emid, inventory_id, set, condition, acquired
   price/date, note join keys) and the TCG MP side (live listing id/price/quantity
   and the sold order(s) with status/qty/price), plus an `assessment` column
   explaining in plain English why each card was flagged and what's recommended.
   Summarise: how many candidates, by confidence tier, with card names and the
   orders they were sold in — quoting the `assessment` for the notable ones.
   Surface anything ambiguous (medium-confidence, cancelled-order matches) for the
   operator to physically verify against the card in hand.

3. **Ask to apply.** Present the candidate list and ask whether to proceed with
   marking sold + removing + delisting. Do not apply without explicit confirmation
   (unless `--apply` was passed).

4. **Apply (on confirmation).** Re-run with `dry_run=False` (and any
   `apply_actions` / `min_confidence` narrowing the operator chose):
   ```bash
   python -c "from workflows.purchases.tasks.sold_inventory_radar import radar_sold_inventory; \
     print(radar_sold_inventory(dry_run=False, last_x_days=<DAYS>, source='<SOURCE>', min_confidence='<CONF>'))"
   ```

5. **Report.** Print the summary line, the path to the review CSV
   (`results/sold_inventory_radar-<ts>.csv`), and remind the operator that every
   removed/marked item is in that file + the `tcg-mp-sold-radar` ES index for
   physical verification.

## Notes

- Confidence: **high** = the EchoMTG note's exact `tcg_mp_listing_id` was sold and
  is still listed; **medium** = product_id + foil match. Start with
  `--min-confidence high` if you want the safest first pass.
- The radar only acts on items that are *both* still in inventory *and* still
  actively listed — it won't touch a card you've already cleaned up.
- It depends on `generate_tcg_mappings` having written notes and on
  `generate_audit_for_tcg_orders` (now tracking Cancelled/Not Received) for the ES
  feed; the live poll covers gaps so it also works standalone.
