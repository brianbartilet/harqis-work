Regenerate the frontend task catalogue from all `workflows/*/tasks_config.py` files.

The generator writes **`frontend/registry.json`** (gitignored — regenerated locally per machine). `frontend/registry.py` is the hand-written loader that reads that JSON at runtime; it is **not** regenerated and must not be hand-edited to add tasks.

Run the generator and report what changed:

```bash
cd $REPO_ROOT && python frontend/generate_registry.py
```

Where `$REPO_ROOT` is the root of the harqis-work repository (the directory containing `frontend/`, `workflows/`, `apps/`).

After running, summarise:
- Which workflows were processed
- Any new tasks detected
- Any manual-only tasks preserved
- Whether the file was updated or was already up to date

## How discovery works (and why a workflow may be skipped)

For each `workflows/*/tasks_config.py`, the generator (`_find_beat_dict`) takes **the first module-level dict whose keys *all* start with `run-job--`**. Per-task it overwrites `task_path` / `queue` / `kwargs` from the beat entry and preserves `label` / `description` / `schedule` / `manual_only` from the existing `registry.json`. The full contract lives in [`workflows/README.md`](../../../workflows/README.md) → "Frontend registry mapping".

A `Skipped: no run-job--* dict found` line is **expected** for:
- **Empty files** (e.g. `finance`) and empty dicts.
- **Disabled workflows** — a dict whose name starts with `_` is intentionally ignored (e.g. `knowledge` parks its entries under `_DISABLED__WORKFLOW_KNOWLEDGE`).
- **Scaffolds** (`.template`) that use a non-`run-job--` key.

But the same message also fires for a **real bug**: the discovery is **all-or-nothing**, so if even one key in the dict does not start with `run-job--`, the whole workflow vanishes. If a workflow you expect is missing, suspect a malformed key. The classic cause is a task "disabled" with a triple-quoted `"""..."""` block inside the dict literal — Python concatenates it with the next key string into one malformed key (and silently swallows that next task). The fix is to comment the disabled task with real `#` lines. To diagnose, load the dict and print its keys:

```bash
python3 -c "import importlib.util,sys; sys.path.insert(0,'.'); s=importlib.util.spec_from_file_location('m','workflows/<name>/tasks_config.py'); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); d=next(v for v in vars(m).values() if isinstance(v,dict) and v); [print(repr(k)[:80]) for k in d]"
```
