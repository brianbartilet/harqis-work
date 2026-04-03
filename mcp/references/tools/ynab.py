import logging

from mcp.server.fastmcp import FastMCP
from apps.ynab.config import CONFIG
from apps.ynab.references.web.api.budgets import ApiServiceYNABBudgets
from apps.ynab.references.web.api.transactions import ApiServiceYNABTransactions
from apps.ynab.references.web.api.user import ApiServiceYNABUser

logger = logging.getLogger("harqis-mcp.ynab")


def register_ynab_tools(mcp: FastMCP):

    @mcp.tool()
    def get_ynab_budgets() -> list[dict]:
        """Get all YNAB budgets for the configured user."""
        logger.info("Tool called: get_ynab_budgets")
        service = ApiServiceYNABBudgets(CONFIG)
        result = service.get_budgets()
        budgets = result.get("budgets", [])
        logger.info("get_ynab_budgets returned %d budget(s)", len(budgets))
        return budgets

    @mcp.tool()
    def get_ynab_budget_summary(budget_id: str) -> dict:
        """Get summary information for a specific YNAB budget.

        Args:
            budget_id: The YNAB budget UUID (e.g. 'last-used' or a full UUID)
        """
        logger.info("Tool called: get_ynab_budget_summary budget_id=%s", budget_id)
        service = ApiServiceYNABBudgets(CONFIG)
        result = service.get_budget_info(budget_id)
        budget = result.get("budget", result)
        logger.info("get_ynab_budget_summary name=%s", budget.get("name") if isinstance(budget, dict) else "?")
        return budget

    @mcp.tool()
    def get_ynab_accounts(budget_id: str) -> list[dict]:
        """Get all accounts in a YNAB budget.

        Args:
            budget_id: The YNAB budget UUID
        """
        logger.info("Tool called: get_ynab_accounts budget_id=%s", budget_id)
        service = ApiServiceYNABBudgets(CONFIG)
        result = service.get_accounts(budget_id)
        accounts = result.get("accounts", [])
        logger.info("get_ynab_accounts returned %d account(s)", len(accounts))
        return accounts

    @mcp.tool()
    def get_ynab_categories(budget_id: str) -> list[dict]:
        """Get all category groups and categories for a YNAB budget.

        Args:
            budget_id: The YNAB budget UUID
        """
        logger.info("Tool called: get_ynab_categories budget_id=%s", budget_id)
        service = ApiServiceYNABBudgets(CONFIG)
        result = service.get_categories(budget_id)
        groups = result.get("category_groups", [])
        logger.info("get_ynab_categories returned %d group(s)", len(groups))
        return groups

    @mcp.tool()
    def get_ynab_transactions(budget_id: str) -> list[dict]:
        """Get all transactions for a YNAB budget.

        Args:
            budget_id: The YNAB budget UUID
        """
        logger.info("Tool called: get_ynab_transactions budget_id=%s", budget_id)
        service = ApiServiceYNABTransactions(CONFIG)
        result = service.get_transactions(budget_id)
        transactions = result.get("transactions", [])
        logger.info("get_ynab_transactions returned %d transaction(s)", len(transactions))
        return transactions

    @mcp.tool()
    def get_ynab_account_transactions(budget_id: str, account_id: str) -> list[dict]:
        """Get all transactions for a specific account within a YNAB budget.

        Args:
            budget_id: The YNAB budget UUID
            account_id: The YNAB account UUID
        """
        logger.info("Tool called: get_ynab_account_transactions budget_id=%s account_id=%s", budget_id, account_id)
        service = ApiServiceYNABTransactions(CONFIG)
        result = service.get_transactions_per_account(budget_id, account_id)
        transactions = result.get("transactions", [])
        logger.info("get_ynab_account_transactions returned %d transaction(s)", len(transactions))
        return transactions

    @mcp.tool()
    def get_ynab_user() -> dict:
        """Get the YNAB user profile for the configured credentials."""
        logger.info("Tool called: get_ynab_user")
        service = ApiServiceYNABUser(CONFIG)
        result = service.get_user_info()
        user = result.get("data", {}).get("user", result) if isinstance(result, dict) else result
        logger.info("get_ynab_user id=%s", user.get("id") if isinstance(user, dict) else "?")
        return user
