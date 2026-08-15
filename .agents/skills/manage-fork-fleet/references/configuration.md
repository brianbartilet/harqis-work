# Fleet configuration

`fork-fleet.toml` contains shared defaults. Add explicit repositories either as
compact strings in `fleet.repositories` or as tables:

```toml
[[repositories]]
repository = "owner/repository"
default_branch = "main"
fork_kind = "manual-clone"
```

Machine-only paths belong in ignored `fork-fleet.local.toml`:

```toml
[[repositories]]
repository = "owner/repository"
local_path = "D:/GIT/repository"
default_branch = "main"
```

The committed registry wins for membership; local entries enrich it. GitHub
fallback searches configured owners, accepts GitHub forks automatically, and
accepts independent derivatives when their default branch contains
`fork-manifest.toml`. Legacy fresh-history derivatives can also be recognized
when their README explicitly references `harqis-work` or the configured source
repository. Manual repositories without detectable lineage must be registered.

Persisted candidate plans use `fleet.plan_dir` (default
`.harqis-data/fork-fleet/plans`). Rollout reports are written beside that directory under
`.harqis-data/fork-fleet/rollouts`. These paths must remain ignored runtime data.
