Regenerate `frontend/registry.py` from all `workflows/*/tasks_config.py` files.

Run the registry generator and report what changed:

```bash
cd $REPO_ROOT && python frontend/generate_registry.py
```

Where `$REPO_ROOT` is the root of the harqis-work repository (the directory containing `frontend/`, `workflows/`, `apps/`).

After running, summarise:
- Which workflows were processed
- Any new tasks detected
- Any manual-only tasks preserved
- Whether the file was updated or was already up to date
