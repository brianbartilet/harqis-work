"""
workflows/knowledge/tasks/answer.py

End-to-end RAG answer:

    question
      → Gemini embed (RETRIEVAL_QUERY)
      → sqlite_vec KNN
      → Anthropic (Haiku 4.5 by default) with cited context
      → answer with [n] citations + Sources: footer

Callable two ways:
  - Direct invocation from another task (sync)
  - As a Celery task via `.delay(question=...)` for async / scheduled use

Cost note: pass `model="claude-haiku-4-5-20251001"` (already the default in
tasks_config) so this stays cheap. Do not raise it via the Anthropic config
default — that is shared by Sonnet-class workflows.
"""

from __future__ import annotations

from typing import Any, Optional

from core.apps.sprout.app.celery import SPROUT
from core.apps.es_logging.app.elasticsearch import log_result
from core.utilities.logging.custom_logger import create_logger

from apps.antropic.config import get_config as get_anthropic_config
from apps.antropic.references.web.base_api_service import BaseApiServiceAnthropic

from workflows.knowledge.prompts import load_prompt
from workflows.knowledge.retriever import retrieve, format_context

_log = create_logger("knowledge.answer")

_DEFAULT_HAIKU = "claude-haiku-4-5-20251001"


def answer_question(
    question: str,
    *,
    k: int = 5,
    source: Optional[str] = None,
    cfg_id__anthropic: str = "ANTHROPIC",
    model: str = _DEFAULT_HAIKU,
    max_tokens: int = 1024,
) -> dict[str, Any]:
    """Synchronous helper — used by both the Celery task and the MCP tool."""
    if not question.strip():
        return {"answer": "", "hits": [], "model": model, "error": "empty question"}

    hits = retrieve(question, k=k, source=source)
    if not hits:
        return {
            "answer": "I couldn't find anything in the indexed knowledge base for that question.",
            "hits": [],
            "model": model,
        }

    context = format_context(hits)
    system_prompt = load_prompt("rag_answer")

    user_msg = (
        f"Question: {question}\n\n"
        f"Context snippets:\n\n{context}"
    )

    client = BaseApiServiceAnthropic(get_anthropic_config(cfg_id__anthropic))
    if not client.base_client:
        raise RuntimeError("Anthropic client failed to initialize")

    response = client._with_backoff(
        client.base_client.messages.create,
        model=model,
        max_tokens=max_tokens,
        system=system_prompt,
        messages=[{"role": "user", "content": user_msg}],
    )

    answer_text = response.content[0].text.strip() if response.content else ""

    return {
        "answer": answer_text,
        "hits": [
            {"id": h["id"], "ref": h["ref"], "source": h["source"], "distance": h["distance"]}
            for h in hits
        ],
        "model": model,
        "question": question,
    }


@SPROUT.task()
@log_result()
def answer(**kwargs):
    """Celery wrapper for `answer_question` — schedule or `.delay()` it.

    Args:
        question:           The user question to answer.
        k:                  Top-k retrieval (default 5).
        source:             Optional source filter, e.g. 'notion'.
        cfg_id__anthropic:  Anthropic config key (default 'ANTHROPIC').
        model:              Override generation model. Default Haiku 4.5.
        max_tokens:         Generation cap (default 1024).
    """
    question = kwargs.get("question", "")
    return answer_question(
        question=question,
        k=int(kwargs.get("k", 5)),
        source=kwargs.get("source"),
        cfg_id__anthropic=kwargs.get("cfg_id__anthropic", "ANTHROPIC"),
        model=kwargs.get("model", _DEFAULT_HAIKU),
        max_tokens=int(kwargs.get("max_tokens", 1024)),
    )
