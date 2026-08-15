# Git Forks workflow

### `scan_fork_fleet`

**Goal:** Discover accessible harqis-work forks, measure drift, and preserve one HFL entry for every fork plus a fleet summary.

**Apps chained:**
1. `apps/git` → discovers repositories and calculates commit, patch, file, capability, branch, PR, and CI drift.
2. `workflows/hfl` → durably writes canonical source `git`, tag `git-forks` entries to Markdown and Elasticsearch.

**Schedule:** Active in Beat every Sunday at 06:00 local time.

**Queue:** `WorkflowQueue.HOST`

**OS:** cross-platform

**Required config keys:** none

**Required env vars:** none beyond existing authenticated `gh` CLI and HFL host configuration.

**Data flow:**
```
registry + GitHub fallback → Git comparison/cache → JSON report → per-fork HFL entries + fleet summary
```

**Outputs / side effects:** Fetches remote refs, writes `.harqis-data/fork-fleet/latest.json`, then dual-writes one HFL entry per fork and one fleet summary.

**Failure behavior:** Repository failures are isolated and included in both the report and that fork's HFL entry; remaining forks continue.
