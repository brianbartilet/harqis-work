# Alias-first, occurrence-ranked consolidation

## Implemented algorithm

1. Reuse `entity_candidates` inverted indexes over canonical/alias names, partial
   hints, contacts and trigrams. This is candidate retrieval, never an identity verdict.
   No new per-alias LLM search is needed. Existing shortlist/discovery limits remain.
2. Rank the complete pending ledger by `(signal_tier, type_priority, -anchor.related_items,
   anchor_id, -contact, -exact_name_or_alias, -partial, -fuzzy, -other.related_items,
   pair_id)`. Type priority is people, companies, tools, pets, apps, games, then other
   kinds. Signal tiers are direct contact/identifier, exact name/alias, then fuzzy,
   so easy media matches precede weak fuzzy people matches. `related_items` counts
   unique non-audit entries, not raw word mentions.
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

## Claimed review packets

Servers advertising `claimed-anchor-packets-v1` expose `POST /consolidation/{run}/claims`
with `worker_id`, `max_pairs` (1–20, default 8), `max_bytes` (4,096–1,000,000,
default 100,000), and `lease_seconds` (60–3,600, default 900). Prefer this path to
the legacy page-local grouping in steps 3–4 above. It reconciles stale endpoints,
checks changed-input fingerprints, discovers new work, then chooses an anchor
from the complete available ledger. Targeted anchor expansion reuses the indexed
50-candidate discovery pool and selects up to 20 candidates per anchor. Existing
ledger edges also participate. This increases bounded coverage without claiming
exhaustive discovery or treating graph connectivity as identity proof.

Packet size is applied after selecting the neighborhood. Evidence appears once per
entity; `claim.remaining_for_anchor` makes unissued edges visible. The byte budget
counts serialized UTF-8 entities and pairs; `evidence_bytes` is not token usage.
No excerpt is silently shortened to fit. An oversized first edge returns
`required_bytes` without reserving work. Other workers cannot claim overlapping IDs.
The same worker ID retrieves its active packet; use a distinct ID for each reviewer.
`POST /claims/{token}` renews or releases a claim. Expired leases are reclaimable.

Supply `claim_token` separately from identity decisions in batch/group requests.
It is deliberately excluded from merge fingerprints so recovery of an already
committed operation works after lease expiry. A token never bypasses snapshots,
curated profiles, contradictions, blocks, or source checks. The legacy writer path
cannot bypass a currently active claim. Commits still serialize under the matching
lock; review concurrency is owned by the calling agent runtime.

`POST /consolidation/{run}/evidence` takes `entity_id`, 1–4 `entry_ids` and optional
`claim_token`. It verifies source content hashes and membership, then caches up to
6,000 characters around the stored mention across the entity's pending comparisons.
Hydrated packets retain at most 12 active snippets and eight excluded snippets;
`truncated` flags bounded original context. Original-entry locators remain available.
Facts may specify `left_entry_id`/`right_entry_id`. Ordinary two-fact approval needs
two distinct origins on each side, not two excerpts of the same capture. Recognized
HARQIS directory captures are retained as excluded provenance. Classification is
conservative and depends on available source/title/context, not a universal detector.

Claims automatically reconcile/checkpoint; explicit `POST /checkpoint` also records
partial counts and discovers changed inputs without closing the run. No pending
comparison is marked reviewed by checkpointing. New candidate versions retain old
decisions for audit. A same-run retry does not rediscover unchanged deferred work.

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
- One matching lock, run load and run save for ordinary batches, retaining per-item
  errors and transaction receipts. Every merge invalidates consumed endpoints.
- Run timings for load, index construction, lock wait, batch and claim operations;
  logs measure actual save duration without rewriting the run solely for timing.
  These measurements exclude agent/model time, which must come from the caller.

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

Every fifth new claim selects the oldest pending comparison for fairness. Claims and
checkpoints permit fresh discovery during unfinished runs and expose partial counts.
Final HFL/Telegram reporting still waits for no pending comparisons. This change does
not implement bounded-run finalization, partial HFL delivery, cross-run semantic
verdict caching, worker process supervision or a new runtime/model selector.

Run storage now uses separate pair rows and content-addressed evidence rows, updating
only changed rows transactionally. Legacy JSON runs migrate on their next write.
Metadata remains JSON; reads and serialization still traverse the run in memory.
Search features persist by versioned search inputs; each snapshot builds postings
and counts once, reused for changed-seed discovery and anchor expansion. Exact
name/contact buckets emit highest-activity anchor stars without the fuzzy cap.
Fuzzy discovery skips repeated postings for homogeneous name buckets larger than
256 entities, already covered by exact stars, and retains the 50-member pool.
Ambiguous leaf-to-leaf identities and fuzzy variants outside the pool may be missed.
The discovery version forces one refresh for existing runs/checkpoints on upgrade.
API/CLI/skill must be deployed compatibly before live execution;
status advertises `atomic-anchor-groups-v1`, compact output `anchor-packets-v1`.
Legacy calls remain supported without new flags. Never solve a deployment mismatch
by bypassing validation through manual merge routes.

Use isolated synthetic corpus tests, including group undo, identical replay after
lost run save, cross-leaf conflicts/exclusions, owner auth, changed snapshots/store
revisions, curated identity protection, page ordering and API/CLI compatibility.
Do not benchmark by merging production entities.
