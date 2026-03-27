Scaffold a new workflow under `workflows/` by copying the template.

The argument $ARGUMENTS is the new workflow name in snake_case (e.g. `finance`, `social`).

Steps:
1. Copy `workflows/.template/` to `workflows/$ARGUMENTS/`.
2. Rename placeholder references inside the copied files from `template` / `TEMPLATE` to the new workflow name.
3. Register the workflow beat schedule in `workflows/config.py` by importing and merging the new `tasks_config.py` dict.
4. If the workflow should appear in the frontend dashboard, add an entry to `WORKFLOW_SOURCES` in `frontend/generate_registry.py` and re-run the registry generator.
5. Remind the user to:
   - Define tasks in `workflows/<name>/tasks/`
   - Add the workflow to the Workflow Inventory table in `CLAUDE.md`
   - Add any required queue to the Celery worker start scripts in `scripts/`
