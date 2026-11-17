"""Shared CLI/MCP surface; provider calls stay in the service layer."""
import logging
from mcp.server.fastmcp import FastMCP
from apps.typesafe.config import CONFIG
from apps.typesafe.references.web.api.system_one import ApiServiceTypeSafeDecisions

logger = logging.getLogger('harqis-mcp.typesafe')


def register_typesafe_tools(mcp: FastMCP):
    @mcp.tool()
    def list_typesafe_models() -> list[dict]:
        """List models accessible to the configured TypeSafe account."""
        logger.info('list_typesafe_models called')
        result = ApiServiceTypeSafeDecisions(CONFIG).list_models()
        logger.info('list_typesafe_models returned %d models', len(result))
        return result

    @mcp.tool()
    def analyze_typesafe_decision(template: str, state: dict) -> dict:
        """Send supplied context to TypeSafe for a billed recommendation; persist a local receipt.

        Never assigns agents or executes actions. Thresholds are provisional.
        Args:
            template: Versioned template, currently action_triage_v1.
            state: action (title, description) and candidate_agents (1–20 objects,
                each with unique id, name and capabilities list). Maximum 48 KB.
        """
        logger.info('analyze_typesafe_decision called')
        result = ApiServiceTypeSafeDecisions(CONFIG).analyze_decision(template, state)
        logger.info('analyze_typesafe_decision status=%s receipt=%s', result['status'], result['receipt_id'])
        return result
