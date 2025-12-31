from collections import defaultdict
from typing import Any


def log_mp_summary(
    results: list[dict[str, Any]],
    *,
    title: str,
    log,
    created_key: str = "created",
    updated_key: str = "updated",
    status_key: str = "status",
    ok_status: str = "ok",
    skipped_status: str = "skipped",
    error_status: str = "error",
    pid_key: str = "pid",
    max_failures_total: int = 10,
    max_failures_per_worker: int = 3,
) -> None:
    """
    Reusable summary logger for multiprocessing batch results.

    Expects each result dict to contain at least:
      - status (ok/skipped/error)
      - optionally pid (recommended) for grouping
      - optionally created/updated boolean flags

    Notes:
      - If pid is missing, grouping will fall back to "unknown".
      - Ordering is stable by pid to keep logs grouped.
    """
    results = results or []
    total = len(results)

    # Primary counters
    created = sum(1 for r in results if r.get(created_key))
    updated = sum(1 for r in results if r.get(updated_key))
    skipped = sum(1 for r in results if r.get(status_key) == skipped_status)
    failed = [r for r in results if r.get(status_key) == error_status]

    # Group by worker pid (multiprocessing identity)
    by_pid: dict[Any, list[dict[str, Any]]] = defaultdict(list)
    for r in results:
        by_pid[r.get(pid_key, "unknown")].append(r)

    # Headline summary
    log.info(
        "%s completed | total=%d created=%d updated=%d skipped=%d failed=%d workers=%d",
        title,
        total,
        created,
        updated,
        skipped,
        len(failed),
        len(by_pid),
    )

    # Per-worker summary (ordered)
    for pid in sorted(by_pid, key=lambda x: (str(x) != "unknown", str(x))):
        worker_results = by_pid[pid]
        w_total = len(worker_results)
        w_created = sum(1 for r in worker_results if r.get(created_key))
        w_updated = sum(1 for r in worker_results if r.get(updated_key))
        w_skipped = sum(1 for r in worker_results if r.get(status_key) == skipped_status)
        w_failed = [r for r in worker_results if r.get(status_key) == error_status]

        log.info(
            "Worker pid=%s | total=%d created=%d updated=%d skipped=%d failed=%d",
            pid,
            w_total,
            w_created,
            w_updated,
            w_skipped,
            len(w_failed),
        )

        # Limit per-worker failure logs
        for r in w_failed[:max_failures_per_worker]:
            log.error(
                "Worker pid=%s failure | card=%s error=%s payload=%s",
                pid,
                r.get("card"),
                r.get("error"),
                {k: v for k, v in r.items() if k not in ("error",)},  # keep it readable
            )

    # Also log a small overall sample of failures (optional)
    for r in failed[:max_failures_total]:
        log.error("Failure sample | %s", r)