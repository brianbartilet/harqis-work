# Alias-first, occurrence-ranked consolidation

## Implemented algorithm

1. Reuse `entity_candidates` inverted indexes over canonical/alias names, partial
   hints, contacts and trigrams. This is candidate retrieval, never an identity verdict.
   No new per-alias LLM search is needed. Existing shortlist/discovery limits remain.
2. Rank the complete pending ledger by `(type_priority, -anchor.related_items,
   anchor_id, -contact, -exact_name_or_alias, -partial, -fuzzy, -other.related_items,
   pair_id)`. Type priority is people, companies, tools, apps, pets, games, then other
   kinds. `related_items` counts unique non-audit entries, not raw word mentions.
3. Bound the response to at most 20 comparisons. In compact mode, put evidence in
   `entities[id]` exactly once; comparison records refer through `left_id`/`right_id`.
   Reject inconsistent snapshots rather than silently overwriting one. Keep every
   source snippet and its metadata; this is deduplication, not evidence summarization.
4. Visit high-count anchors first and propose disjoint same-type stars of available
   comparisons. `groups[].anchor_id`, `pair_ids` and `entity_ids` describe a work packet.
   A packet can contain one edge and need not span every alias in the corpus. Deferred
   pages return unassigned comparisons under `ungrouped_pair_ids`; none are discarded.
5. Read the anchor evidence once and assess each leaf independently. Quotes retain
   the original pair's left/right orientation. After per-edge approval, check ALL
   selected members for incompatible external identifiers, people/organization roles,
   curated identity details and explicit keep-separate decisions. Similarity is not
   transitive proof. Remove uncertain candidates rather than approving the component.
6. Commit 2–20 accepted edges in one authorized `group` operation, not sequential
   overlapping `batch` merges. There are 3–21 distinct same-type members and one anchor.
   A one-edge packet still uses the ordinary decision/batch path.
7. Under the existing matching lock, validate pending/same-run membership, per-edge
   source-backed facts, unchanged snapshots, all member-pair unmerge exclusions,
   known in-run cross-member separate/contradiction decisions, external identities
   and curated-profile compatibility. Verify the store revision did not change
   during snapshot read; the existing commit checks revision again transactionally.
8. Reuse the established N-way preview/commit transaction. Choose the canonical name
   using preferred/curated protections, not merely frequency. Retain alias provenance,
   full operation receipt and undo. Every approved edge receives the SAME receipt;
   other pending comparisons touching consumed IDs become stale. Do not copy their
   old approvals to the resulting entity. Fresh discovery requires its normal lifecycle.
9. Retry the identical payload after unknown outcomes. A deterministic operation ID
   plus receipt recovers commit-before-run-save interruptions without a second merge.
   Report unique operation IDs as merged groups, separately from comparison counts.

## Group payload

`group RUN_ID --file GROUP.json` submits `POST /consolidation/{run_id}/groups`.
The top-level cross-member contradiction check is mandatory. Do not submit the literal
illustrative placeholders below. Both facts must quote actual evidence from their
own pair, not a quotation copied from a different leaf.

```json
{
  "anchor_id": "EXISTING_ANCHOR_ID",
  "contradictions": [],
  "decisions": {
    "EXISTING_ANCHOR_PAIR_1": {
      "decision": "merge",
      "reason": "Specific identifying context independently establishes this member.",
      "facts": [{"left_quote": "Exact left-side source passage", "right_quote": "Exact right-side source passage", "explanation": "The specific shared identifying fact"}],
      "contradictions": [], "aliases": [], "partial_aliases": []
    },
    "EXISTING_ANCHOR_PAIR_2": {
      "decision": "merge",
      "reason": "Specific identifying context independently establishes this member.",
      "facts": [{"left_quote": "Exact left-side source passage", "right_quote": "Exact right-side source passage", "explanation": "The specific shared identifying fact"}],
      "contradictions": [], "aliases": [], "partial_aliases": []
    }
  }
}
```

Ordinary, non-strong matches require additional independent facts as documented in
SKILL.md. API structural validation and source-quote checks do not replace a semantic
identity assessment or guarantee that the supplied facts truly identify someone.

## Lower-cost reasoning protocol

Implemented now:
- Indexed shortlist discovery rather than per-entity/all-pairs LLM searches.
- Global type/occurrence ranking and bounded status pages (`--limit 1..20`).
- Lossless per-page evidence deduplication plus disjoint anchor proposals.
- One reversible commit for a high-confidence star, avoiding repeated collection
  reconstruction, stale-anchor failures and redundant write round trips per leaf.
- Compact CLI JSON without pretty-print whitespace; one structured batch response.

Operator strategy (not a new scheduler/model router):
- Start with 3–8 candidate aliases per reasoning packet. Use a smaller status page
  when evidence is large; split large packets without dropping identifying context.
- Keep deterministic sorting, grouping, hash calculation and result counting in
  code, not model output. Ask only for concise verdicts/reasons/quoted facts; no
  repeated biographies or verbose chain-of-thought dumps.
- Reuse a read-only evidence cache keyed by entity ID AND evidence/profile fingerprint
  within a run if the caller supports it. Invalidate touched IDs after every write;
  never reuse stale verdicts. A persistent cross-run cache is a future optimization,
  not implemented by this change.
- Ambiguous packets need targeted original-entry retrieval or stronger review, not
  larger indiscriminate prompts. Keep unresolved identities separate. Do not change
  model providers, scheduled jobs or service settings without explicit authorization.
- If collecting budget data, record serialized UTF-8 bytes and actual model input/
  output tokens, latency, reviewed comparisons and accepted groups. Shrink future
  packets when input is high; increase only after stable precision. Byte savings
  are a reproducible proxy, NOT measured token/currency savings.

## Limits and rollout

Strict priority can starve lower-priority types until higher tiers clear. Unfinished
runs currently block fresh discovery, and finish/reporting still waits for no pending
comparisons. This change does not implement fairness quotas, bounded-run finalization,
incremental progress reports, cross-run caching or a new runtime/model selector.

Compact packets do not remove server-side full-run JSON storage/rewrite costs. They
also do not promise exhaustive alias discovery: existing candidate caps/incremental
seed rules remain. API/CLI/skill must be deployed compatibly before live execution;
status advertises `atomic-anchor-groups-v1`, compact output `anchor-packets-v1`.
Legacy calls remain supported without new flags. Never solve a deployment mismatch
by bypassing validation through manual merge routes.

Use isolated synthetic corpus tests, including group undo, identical replay after
lost run save, cross-leaf conflicts/exclusions, owner auth, changed snapshots/store
revisions, curated identity protection, page ordering and API/CLI compatibility.
Do not benchmark by merging production entities.
