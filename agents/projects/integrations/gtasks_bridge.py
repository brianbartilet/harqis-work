"""
GTasksBridge — sync Google Tasks "Agents Tasks" lists with the Trello kanban board.

Inbound (gtasks → trello):
    Each cycle, list non-completed tasks in the configured "Agents Tasks" list
    on every configured Google account. New tasks get a Trello card created in
    the orchestrator's intake column (`Ready`), an LLM-enriched description, and
    a back-reference written into the gtask's notes pointing to the Trello card.
    The gtask title is prefixed with `|Pending| ` so the user immediately sees
    that the agent has picked it up.

Outbound (trello → gtasks):
    For every recorded binding, look up the linked card's current column and
    rewrite the gtask title with a `|<Status>| ` prefix that mirrors the kanban
    list (`Pending`, `In Progress`, `Blocked`, `Failed`). When the card lands in
    `Done`, the gtask is marked `status='completed'` (and the prefix stripped).
    `In Review` is intentionally NOT reflected back — mid-cycle review is a
    kanban-internal concern, not something the user filed the original task to
    track.

State lives in `.run/gtasks_bindings.json`. Every cycle is idempotent — a
re-run re-applies current truth without duplicating cards.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

import requests

from agents.projects.orchestrator.lists import Lists
from agents.projects.trello.client import TrelloClient
from apps.apps_config import CONFIG_MANAGER
from apps.google_apps.references.web.api.tasks import ApiServiceGoogleTasks

log = logging.getLogger(__name__)


# Mapping from Trello list name → status prefix written to the gtask title.
# `None` means "do not reflect this state back to gtasks".
# `Lists.DONE` is handled specially (mark complete + strip prefix).
_STATUS_PREFIX: dict[str, Optional[str]] = {
    Lists.READY:       "Pending",
    Lists.PENDING:     "Pending",
    Lists.IN_PROGRESS: "In Progress",
    Lists.BLOCKED:     "Blocked",
    Lists.FAILED:      "Failed",
    Lists.IN_REVIEW:   None,
    Lists.DONE:        None,
}

# Matches a leading `|<anything>| ` so we can swap prefixes idempotently
# without piling up `|Pending| |In Progress| ...`.
_PREFIX_RE = re.compile(r"^\|[^|]+\|\s*")

_TRELLO_BASE = "https://api.trello.com/1"


def _strip_prefix(title: str) -> str:
    return _PREFIX_RE.sub("", title or "").strip()


def _apply_prefix(title: str, prefix: Optional[str]) -> str:
    base = _strip_prefix(title)
    if not prefix:
        return base
    return f"|{prefix}| {base}"


# ── Data ─────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class GTasksAccount:
    """One Google account that owns an 'Agents Tasks' list to watch."""
    name: str          # human-readable label (e.g. "personal", "work")
    config_key: str    # apps_config.yaml section name


@dataclass
class Binding:
    """Persistent link between one gtask and one Trello card."""
    gtask_id: str
    tasklist_id: str
    account: str           # GTasksAccount.name
    card_id: str
    last_status: str = ""  # last Trello list name reflected back to the gtask


# ── State persistence (atomic write to `.run/gtasks_bindings.json`) ──────────

def _load_state(path: Path) -> dict[str, Binding]:
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        log.warning("gtasks state file at %s is corrupt — starting fresh", path)
        return {}
    out: dict[str, Binding] = {}
    for entry in raw.get("bindings", []):
        try:
            b = Binding(**entry)
        except TypeError:
            # Schema drift — silently drop unknown fields rather than crashing.
            b = Binding(
                gtask_id=entry.get("gtask_id", ""),
                tasklist_id=entry.get("tasklist_id", ""),
                account=entry.get("account", ""),
                card_id=entry.get("card_id", ""),
                last_status=entry.get("last_status", ""),
            )
        if b.gtask_id and b.card_id:
            out[b.gtask_id] = b
    return out


def _save_state(path: Path, state: dict[str, Binding]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    payload = {"bindings": [asdict(b) for b in state.values()]}
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(path)


# ── Account resolution ───────────────────────────────────────────────────────

def load_accounts(
    account_keys: Iterable[str],
) -> list[tuple[GTasksAccount, ApiServiceGoogleTasks]]:
    """Resolve apps_config keys into (GTasksAccount, gtasks-client) tuples.

    Skips keys that aren't present in the config — logs a warning so
    misconfigured accounts don't kill the whole sync cycle.
    """
    out: list[tuple[GTasksAccount, ApiServiceGoogleTasks]] = []
    for key in account_keys:
        try:
            cfg = CONFIG_MANAGER.get(key)
        except KeyError:
            log.warning("Account config %s not found — skipping", key)
            continue
        if cfg is None:
            log.warning("Account config %s is empty — skipping", key)
            continue
        try:
            svc = ApiServiceGoogleTasks(cfg)
        except Exception as e:  # pragma: no cover — auth wiring varies per host
            log.error("Failed to build Google Tasks client for %s: %s", key, e)
            continue
        # Friendly account name: "GOOGLE_TASKS_PERSONAL" → "personal"
        suffix = key.removeprefix("GOOGLE_TASKS_").lower() if key.startswith("GOOGLE_TASKS_") else key.lower()
        account = GTasksAccount(name=suffix or "default", config_key=key)
        out.append((account, svc))
    return out


# ── LLM enrichment ───────────────────────────────────────────────────────────

class DescriptionEnricher:
    """Generate a 2-3 paragraph Trello-card description from a bare gtask title.

    Uses Anthropic's messages API. Defaults to Haiku 4.5 (cost-friendly) per the
    project convention; pass `model=...` from the celery schedule to override.
    """

    _SYSTEM_PROMPT = (
        "You are an intake clerk for a small kanban board. A user has filed a "
        "task by adding it to a Google Tasks list called 'Agents Tasks'. Your "
        "job is to expand the bare title into a Trello card description that:\n"
        "- restates the task in one sentence of plain language\n"
        "- enumerates 2-5 likely sub-steps an autonomous agent will need to do\n"
        "- flags any ambiguity the human should clarify before agents pick it up\n"
        "Markdown is fine. No preamble, no closing. Keep it under 250 words."
    )

    def __init__(
        self,
        anthropic_config_key: str = "ANTHROPIC",
        model: str = "claude-haiku-4-5-20251001",
        max_tokens: int = 600,
    ) -> None:
        # Imports are local so test code can mock the bridge without pulling
        # the Anthropic SDK into every test that doesn't need it.
        from apps.antropic.config import get_config as get_anthropic_config
        from apps.antropic.references.web.base_api_service import BaseApiServiceAnthropic

        cfg = get_anthropic_config(anthropic_config_key)
        self._client = BaseApiServiceAnthropic(cfg)
        self._model = model
        self._max_tokens = max_tokens

    def enrich(self, title: str, notes: str = "") -> str:
        if not self._client.base_client:
            raise RuntimeError("Anthropic client failed to initialize")
        user_msg = (
            f"Title: {title}\n\n"
            f"User-provided notes (may be empty):\n{notes or '(none)'}"
        )
        resp = self._client._with_backoff(
            self._client.base_client.messages.create,
            model=self._model,
            max_tokens=self._max_tokens,
            system=self._SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        )
        try:
            return resp.content[0].text.strip()
        except (AttributeError, IndexError):
            return notes or title


# ── Bridge ───────────────────────────────────────────────────────────────────

class GTasksBridge:
    """Bidirectional sync between Google Tasks lists and a Trello kanban board.

    `accounts` is a list of (account, gtasks-service) tuples — one per
    configured Google account. The bridge polls every account on every
    `run_once()` call and shares one Trello board for the resulting cards.

    `enricher` is optional. When omitted, new cards get a placeholder description
    instead of an LLM-generated one — useful for tests and for hosts where the
    Anthropic key is not provisioned.
    """

    def __init__(
        self,
        accounts: list[tuple[GTasksAccount, ApiServiceGoogleTasks]],
        list_name: str,
        board_id: str,
        intake_column: str,
        trello: TrelloClient,
        state_path: Path,
        enricher: Optional[DescriptionEnricher] = None,
    ) -> None:
        self.accounts = accounts
        self.list_name = list_name
        self.board_id = board_id
        self.intake_column = intake_column
        self.trello = trello
        self.state_path = state_path
        self.enricher = enricher
        self.state: dict[str, Binding] = _load_state(state_path)

    # ── Inbound: gtasks → Trello ─────────────────────────────────────────────

    def _resolve_tasklist_id(self, svc: ApiServiceGoogleTasks) -> Optional[str]:
        """Find the tasklist whose title matches `self.list_name` (case-insensitive)."""
        target = self.list_name.strip().lower()
        for tl in svc.list_task_lists():
            if (tl.get("title") or "").strip().lower() == target:
                return tl.get("id")
        return None

    def sync_inbound(self) -> int:
        """Create Trello cards for every new gtask. Returns the number created."""
        created = 0
        for account, svc in self.accounts:
            tasklist_id = self._resolve_tasklist_id(svc)
            if not tasklist_id:
                log.info(
                    "[%s] no tasklist named %r — skipping inbound for this account",
                    account.name, self.list_name,
                )
                continue
            try:
                tasks = svc.list_tasks(tasklist_id=tasklist_id, show_completed=False)
            except Exception as e:
                log.error("[%s] list_tasks failed: %s", account.name, e)
                continue

            for task in tasks:
                gtask_id = task.get("id")
                if not gtask_id or gtask_id in self.state:
                    continue
                if (task.get("status") or "") == "completed":
                    continue

                title = _strip_prefix(task.get("title", "(untitled)"))
                notes = task.get("notes", "") or ""

                description = self._enrich(title, notes)

                try:
                    card = self._create_card(title, description, account)
                except Exception as e:
                    log.error(
                        "[%s] failed to create Trello card for gtask %s: %s",
                        account.name, gtask_id, e,
                    )
                    continue

                card_url = card.get("shortUrl") or card.get("url") or ""
                merged_notes = self._merge_notes(notes, card_url)
                try:
                    svc.update_task(
                        gtask_id,
                        {
                            "title": _apply_prefix(title, "Pending"),
                            "notes": merged_notes,
                        },
                        tasklist_id=tasklist_id,
                    )
                except Exception as e:
                    # Card already created — the link-back is best-effort.
                    log.warning(
                        "[%s] failed to update gtask %s with Trello link: %s",
                        account.name, gtask_id, e,
                    )

                self.state[gtask_id] = Binding(
                    gtask_id=gtask_id,
                    tasklist_id=tasklist_id,
                    account=account.name,
                    card_id=card["id"],
                    last_status=Lists.READY,
                )
                created += 1
                log.info(
                    "[%s] created Trello card %s for gtask %s",
                    account.name, card["id"], gtask_id,
                )
        if created:
            _save_state(self.state_path, self.state)
        return created

    def _create_card(
        self, title: str, description: str, account: GTasksAccount,
    ) -> dict[str, Any]:
        """POST /1/cards directly — TrelloClient does not expose card creation
        because the orchestrator never creates cards (only moves them)."""
        col_id = self.trello._resolve_col_id(self.board_id, self.intake_column)
        body = description + f"\n\n— Source: gtasks/{account.name}"
        r = requests.post(
            f"{_TRELLO_BASE}/cards",
            params={
                **self.trello._auth,
                "idList": col_id,
                "name": title,
                "desc": body,
            },
            timeout=self.trello._timeout,
        )
        r.raise_for_status()
        return r.json()

    def _enrich(self, title: str, existing_notes: str) -> str:
        if not self.enricher:
            return existing_notes or f"# {title}\n\n_No additional context provided._"
        try:
            return self.enricher.enrich(title=title, notes=existing_notes)
        except Exception as e:
            log.warning("Description enrichment failed (%s) — falling back to title", e)
            return existing_notes or f"# {title}"

    @staticmethod
    def _merge_notes(existing: str, card_url: str) -> str:
        """Add (or replace) a `Trello: <url>` line in the gtask notes."""
        existing = (existing or "").rstrip()
        marker = "Trello: "
        kept = [
            line for line in existing.splitlines()
            if not line.strip().startswith(marker)
        ]
        kept.append(f"{marker}{card_url}")
        return "\n".join(kept).strip()

    # ── Outbound: Trello → gtasks ────────────────────────────────────────────

    def sync_outbound(self) -> int:
        """Reflect Trello card status back to the gtask title / status.

        Returns the number of gtasks updated this cycle.
        """
        updated = 0
        terminal: list[str] = []  # binding ids to drop after the cycle

        for gtask_id, binding in list(self.state.items()):
            current_list = self._card_list_name(binding.card_id)
            if current_list is None:
                # Card likely deleted — let go of the binding.
                log.info("Dropping binding %s — card %s no longer fetchable",
                         gtask_id, binding.card_id)
                terminal.append(gtask_id)
                continue

            if current_list == binding.last_status and current_list != Lists.DONE:
                # Already in sync — nothing to do.
                continue

            svc = self._svc_for_account(binding.account)
            if svc is None:
                log.warning(
                    "No service registered for account %r — cannot sync gtask %s",
                    binding.account, gtask_id,
                )
                continue

            try:
                gtask = svc.get_task(binding.gtask_id, binding.tasklist_id)
            except Exception as e:
                # Gtask might have been deleted from the UI — drop the binding.
                log.info("Dropping binding %s — gtask fetch failed (%s)",
                         gtask_id, e)
                terminal.append(gtask_id)
                continue

            title = gtask.get("title", "")

            if current_list == Lists.DONE:
                if (gtask.get("status") or "") != "completed":
                    svc.update_task(
                        binding.gtask_id,
                        {"title": _strip_prefix(title), "status": "completed"},
                        tasklist_id=binding.tasklist_id,
                    )
                    updated += 1
                    log.info(
                        "[%s] gtask %s marked completed (card %s landed in Done)",
                        binding.account, gtask_id, binding.card_id,
                    )
                terminal.append(gtask_id)
                continue

            prefix = _STATUS_PREFIX.get(current_list)
            if prefix is None:
                # `In Review` (or anything else we explicitly skip) — record
                # the status so we don't re-evaluate every cycle.
                binding.last_status = current_list
                continue

            new_title = _apply_prefix(title, prefix)
            if new_title != title:
                svc.update_task(
                    binding.gtask_id,
                    {"title": new_title},
                    tasklist_id=binding.tasklist_id,
                )
                updated += 1
                log.info("[%s] gtask %s title → %r",
                         binding.account, gtask_id, new_title)

            binding.last_status = current_list

        for tid in terminal:
            self.state.pop(tid, None)

        if updated or terminal:
            _save_state(self.state_path, self.state)
        return updated

    def _card_list_name(self, card_id: str) -> Optional[str]:
        """GET /1/cards/{card_id}/list → list.name. Returns None on any error."""
        try:
            r = requests.get(
                f"{_TRELLO_BASE}/cards/{card_id}/list",
                params=self.trello._auth,
                timeout=self.trello._timeout,
            )
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.json().get("name")
        except Exception as e:
            log.warning("Failed to fetch list name for card %s: %s", card_id, e)
            return None

    def _svc_for_account(self, name: str) -> Optional[ApiServiceGoogleTasks]:
        for account, svc in self.accounts:
            if account.name == name:
                return svc
        return None

    # ── Combined ─────────────────────────────────────────────────────────────

    def run_once(self) -> dict[str, int]:
        inbound = self.sync_inbound()
        outbound = self.sync_outbound()
        return {
            "inbound_created": inbound,
            "outbound_updated": outbound,
            "active_bindings": len(self.state),
        }
