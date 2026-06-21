import logging

from mcp.server.fastmcp import FastMCP
from apps.ynab.config import CONFIG
from apps.ynab.references.web.api.budgets import ApiServiceYNABBudgets
from apps.ynab.references.web.api.transactions import ApiServiceYNABTransactions
from apps.ynab.references.web.api.categories import ApiServiceYNABCategories
from apps.ynab.references.web.api.payees import ApiServiceYNABPayees
from apps.ynab.references.web.api.months import ApiServiceYNABMonths
from apps.ynab.references.web.api.scheduled_transactions import ApiServiceYNABScheduledTransactions
from apps.ynab.references.web.api.user import ApiServiceYNABUser

logger = logging.getLogger("harqis-mcp.ynab")


def _build_transaction_body(account_id=None, date=None, amount=None, payee_id=None,
                            payee_name=None, category_id=None, memo=None, cleared=None,
                            approved=None, flag_color=None, frequency=None):
    """Assemble a YNAB transaction/scheduled-transaction object, dropping unset fields."""
    fields = {
        'account_id': account_id,
        'date': date,
        'amount': amount,
        'payee_id': payee_id,
        'payee_name': payee_name,
        'category_id': category_id,
        'memo': memo,
        'cleared': cleared,
        'approved': approved,
        'flag_color': flag_color,
        'frequency': frequency,
    }
    return {k: v for k, v in fields.items() if v is not None}


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

    # ------------------------------------------------------------------ #
    # Transactions — view / create / update / delete                     #
    # ------------------------------------------------------------------ #

    @mcp.tool()
    def get_ynab_transaction(budget_id: str, transaction_id: str) -> dict:
        """View a single YNAB transaction by id.

        Args:
            budget_id: The YNAB budget UUID.
            transaction_id: The transaction UUID.
        """
        logger.info("Tool called: get_ynab_transaction budget_id=%s transaction_id=%s", budget_id, transaction_id)
        service = ApiServiceYNABTransactions(CONFIG)
        result = service.get_transaction(budget_id, transaction_id)
        return result.get("transaction", result)

    @mcp.tool()
    def create_ynab_transaction(budget_id: str, account_id: str, date: str, amount: int,
                                payee_name: str = None, payee_id: str = None,
                                category_id: str = None, memo: str = None,
                                cleared: str = None, approved: bool = True,
                                flag_color: str = None) -> dict:
        """Create a YNAB transaction.

        Args:
            budget_id: The YNAB budget UUID.
            account_id: The account UUID the transaction belongs to.
            date: Transaction date, ISO format (e.g. '2026-06-21').
            amount: Amount in milliunits (1 unit = 1000; outflow is negative, e.g. -50000 = -50.00).
            payee_name: Payee name (creates payee if new). Use this OR payee_id.
            payee_id: Existing payee UUID.
            category_id: Category UUID.
            memo: Free-text memo.
            cleared: 'cleared' | 'uncleared' | 'reconciled'.
            approved: Whether the transaction is approved (default True).
            flag_color: red | orange | yellow | green | blue | purple.
        """
        logger.info("Tool called: create_ynab_transaction budget_id=%s amount=%s", budget_id, amount)
        tx = _build_transaction_body(account_id=account_id, date=date, amount=amount,
                                     payee_id=payee_id, payee_name=payee_name,
                                     category_id=category_id, memo=memo, cleared=cleared,
                                     approved=approved, flag_color=flag_color)
        service = ApiServiceYNABTransactions(CONFIG)
        result = service.create_new_transaction(budget_id, {"transaction": tx})
        logger.info("create_ynab_transaction done budget_id=%s", budget_id)
        return result

    @mcp.tool()
    def update_ynab_transaction(budget_id: str, transaction_id: str, account_id: str = None,
                                date: str = None, amount: int = None, payee_name: str = None,
                                payee_id: str = None, category_id: str = None, memo: str = None,
                                cleared: str = None, approved: bool = None,
                                flag_color: str = None) -> dict:
        """Update an existing YNAB transaction. Only the fields you pass are changed.

        Args:
            budget_id: The YNAB budget UUID.
            transaction_id: The transaction UUID to update.
            (other args): Same meaning as create_ynab_transaction; omit to leave unchanged.
        """
        logger.info("Tool called: update_ynab_transaction budget_id=%s transaction_id=%s", budget_id, transaction_id)
        tx = _build_transaction_body(account_id=account_id, date=date, amount=amount,
                                     payee_id=payee_id, payee_name=payee_name,
                                     category_id=category_id, memo=memo, cleared=cleared,
                                     approved=approved, flag_color=flag_color)
        service = ApiServiceYNABTransactions(CONFIG)
        result = service.update_transaction(budget_id, transaction_id, {"transaction": tx})
        logger.info("update_ynab_transaction done transaction_id=%s", transaction_id)
        return result

    @mcp.tool()
    def delete_ynab_transaction(budget_id: str, transaction_id: str) -> dict:
        """Delete a YNAB transaction by id (destructive).

        Args:
            budget_id: The YNAB budget UUID.
            transaction_id: The transaction UUID to delete.
        """
        logger.info("Tool called: delete_ynab_transaction budget_id=%s transaction_id=%s", budget_id, transaction_id)
        service = ApiServiceYNABTransactions(CONFIG)
        result = service.delete_transaction(budget_id, transaction_id)
        logger.info("delete_ynab_transaction done transaction_id=%s", transaction_id)
        return result

    # ------------------------------------------------------------------ #
    # Categorization — analyze categories and apply to transactions      #
    # ------------------------------------------------------------------ #

    @mcp.tool()
    def analyze_ynab_uncategorized(budget_id: str) -> dict:
        """Analyze a budget for transactions needing a category and return the available
        categories to choose from, so each transaction can be categorized.

        Returns a dict with:
          - `uncategorized`: transactions with no category (id, date, amount, payee_name, memo)
          - `categories`: flat list of assignable categories (id, name, group, hidden)

        Apply a choice with `categorize_ynab_transaction`.

        Args:
            budget_id: The YNAB budget UUID.
        """
        logger.info("Tool called: analyze_ynab_uncategorized budget_id=%s", budget_id)
        cat_service = ApiServiceYNABCategories(CONFIG)
        tx_service = ApiServiceYNABTransactions(CONFIG)

        groups = cat_service.get_categories(budget_id).get("category_groups", [])
        categories = [
            {"id": c.get("id"), "name": c.get("name"),
             "group": g.get("name"), "hidden": c.get("hidden", False)}
            for g in groups for c in g.get("categories", [])
            if not c.get("deleted")
        ]

        transactions = tx_service.get_transactions(budget_id).get("transactions", [])
        uncategorized = [
            {"id": t.get("id"), "date": t.get("date"), "amount": t.get("amount"),
             "payee_name": t.get("payee_name"), "memo": t.get("memo"),
             "approved": t.get("approved")}
            for t in transactions if not t.get("category_id") and not t.get("deleted")
        ]
        logger.info("analyze_ynab_uncategorized %d uncategorized, %d categories",
                    len(uncategorized), len(categories))
        return {"uncategorized": uncategorized, "categories": categories}

    @mcp.tool()
    def categorize_ynab_transaction(budget_id: str, transaction_id: str, category_id: str) -> dict:
        """Assign a category to an existing transaction.

        Args:
            budget_id: The YNAB budget UUID.
            transaction_id: The transaction UUID to categorize.
            category_id: The category UUID to assign.
        """
        logger.info("Tool called: categorize_ynab_transaction transaction_id=%s category_id=%s",
                    transaction_id, category_id)
        service = ApiServiceYNABTransactions(CONFIG)
        result = service.update_transaction(budget_id, transaction_id,
                                            {"transaction": {"category_id": category_id}})
        logger.info("categorize_ynab_transaction done transaction_id=%s", transaction_id)
        return result

    # ------------------------------------------------------------------ #
    # Categories for a specific month                                    #
    # ------------------------------------------------------------------ #

    @mcp.tool()
    def get_ynab_month_category(budget_id: str, month: str, category_id: str) -> dict:
        """Get a single category's data for a specific month (budgeted/activity/balance).

        Args:
            budget_id: The YNAB budget UUID.
            month: Budget month in ISO format (e.g. '2026-06-01') or 'current'.
            category_id: The category UUID.
        """
        logger.info("Tool called: get_ynab_month_category budget_id=%s month=%s", budget_id, month)
        service = ApiServiceYNABCategories(CONFIG)
        result = service.get_month_category(budget_id, month, category_id)
        return result.get("category", result)

    @mcp.tool()
    def update_ynab_month_category(budget_id: str, month: str, category_id: str, budgeted: int) -> dict:
        """Set a category's budgeted (assigned) amount for a specific month.

        Args:
            budget_id: The YNAB budget UUID.
            month: Budget month in ISO format (e.g. '2026-06-01') or 'current'.
            category_id: The category UUID.
            budgeted: Budgeted amount in milliunits (e.g. 100000 = 100.00).
        """
        logger.info("Tool called: update_ynab_month_category budget_id=%s month=%s budgeted=%s",
                    budget_id, month, budgeted)
        service = ApiServiceYNABCategories(CONFIG)
        result = service.update_month_category(budget_id, month, category_id, budgeted)
        logger.info("update_ynab_month_category done category_id=%s", category_id)
        return result.get("category", result)

    # ------------------------------------------------------------------ #
    # Payees                                                             #
    # ------------------------------------------------------------------ #

    @mcp.tool()
    def get_ynab_payees(budget_id: str) -> list[dict]:
        """Get all payees for a YNAB budget.

        Args:
            budget_id: The YNAB budget UUID.
        """
        logger.info("Tool called: get_ynab_payees budget_id=%s", budget_id)
        service = ApiServiceYNABPayees(CONFIG)
        result = service.get_payees(budget_id)
        payees = result.get("payees", [])
        logger.info("get_ynab_payees returned %d payee(s)", len(payees))
        return payees

    # ------------------------------------------------------------------ #
    # Plan — months                                                      #
    # ------------------------------------------------------------------ #

    @mcp.tool()
    def get_ynab_month(budget_id: str, month: str = "current") -> dict:
        """Get the budget plan for a single month (budgeted/activity per category, to-be-budgeted).

        Args:
            budget_id: The YNAB budget UUID.
            month: Budget month in ISO format (e.g. '2026-06-01') or 'current' (default).
        """
        logger.info("Tool called: get_ynab_month budget_id=%s month=%s", budget_id, month)
        service = ApiServiceYNABMonths(CONFIG)
        result = service.get_month(budget_id, month)
        return result.get("month", result)

    @mcp.tool()
    def get_ynab_months(budget_id: str) -> list[dict]:
        """Get the budget plan summary for all months.

        Args:
            budget_id: The YNAB budget UUID.
        """
        logger.info("Tool called: get_ynab_months budget_id=%s", budget_id)
        service = ApiServiceYNABMonths(CONFIG)
        result = service.get_months(budget_id)
        months = result.get("months", [])
        logger.info("get_ynab_months returned %d month(s)", len(months))
        return months

    # ------------------------------------------------------------------ #
    # Scheduled transactions — view / create / update / delete           #
    # ------------------------------------------------------------------ #

    @mcp.tool()
    def get_ynab_scheduled_transactions(budget_id: str) -> list[dict]:
        """Get all scheduled (recurring/future) transactions for a YNAB budget.

        Args:
            budget_id: The YNAB budget UUID.
        """
        logger.info("Tool called: get_ynab_scheduled_transactions budget_id=%s", budget_id)
        service = ApiServiceYNABScheduledTransactions(CONFIG)
        result = service.get_scheduled_transactions(budget_id)
        scheduled = result.get("scheduled_transactions", [])
        logger.info("get_ynab_scheduled_transactions returned %d", len(scheduled))
        return scheduled

    @mcp.tool()
    def get_ynab_scheduled_transaction(budget_id: str, scheduled_transaction_id: str) -> dict:
        """View a single scheduled transaction by id.

        Args:
            budget_id: The YNAB budget UUID.
            scheduled_transaction_id: The scheduled transaction UUID.
        """
        logger.info("Tool called: get_ynab_scheduled_transaction id=%s", scheduled_transaction_id)
        service = ApiServiceYNABScheduledTransactions(CONFIG)
        result = service.get_scheduled_transaction(budget_id, scheduled_transaction_id)
        return result.get("scheduled_transaction", result)

    @mcp.tool()
    def create_ynab_scheduled_transaction(budget_id: str, account_id: str, date: str, amount: int,
                                          frequency: str = "monthly", payee_name: str = None,
                                          payee_id: str = None, category_id: str = None,
                                          memo: str = None, flag_color: str = None) -> dict:
        """Create a scheduled (recurring/future) transaction.

        Args:
            budget_id: The YNAB budget UUID.
            account_id: The account UUID.
            date: First/next occurrence date, ISO format (e.g. '2026-07-01').
            amount: Amount in milliunits (outflow negative).
            frequency: never | daily | weekly | everyOtherWeek | twiceAMonth | every4Weeks |
                       monthly | everyOtherMonth | every3Months | every4Months | twiceAYear |
                       yearly | everyOtherYear (default 'monthly').
            payee_name / payee_id / category_id / memo / flag_color: Optional, as for transactions.
        """
        logger.info("Tool called: create_ynab_scheduled_transaction budget_id=%s freq=%s", budget_id, frequency)
        st = _build_transaction_body(account_id=account_id, date=date, amount=amount,
                                     payee_id=payee_id, payee_name=payee_name,
                                     category_id=category_id, memo=memo, flag_color=flag_color,
                                     frequency=frequency)
        service = ApiServiceYNABScheduledTransactions(CONFIG)
        result = service.create_scheduled_transaction(budget_id, {"scheduled_transaction": st})
        logger.info("create_ynab_scheduled_transaction done budget_id=%s", budget_id)
        return result

    @mcp.tool()
    def update_ynab_scheduled_transaction(budget_id: str, scheduled_transaction_id: str,
                                          account_id: str = None, date: str = None,
                                          amount: int = None, frequency: str = None,
                                          payee_name: str = None, payee_id: str = None,
                                          category_id: str = None, memo: str = None,
                                          flag_color: str = None) -> dict:
        """Update a scheduled transaction. Only the fields you pass are changed.

        Args:
            budget_id: The YNAB budget UUID.
            scheduled_transaction_id: The scheduled transaction UUID to update.
            (other args): Same meaning as create_ynab_scheduled_transaction; omit to leave unchanged.
        """
        logger.info("Tool called: update_ynab_scheduled_transaction id=%s", scheduled_transaction_id)
        st = _build_transaction_body(account_id=account_id, date=date, amount=amount,
                                     payee_id=payee_id, payee_name=payee_name,
                                     category_id=category_id, memo=memo, flag_color=flag_color,
                                     frequency=frequency)
        service = ApiServiceYNABScheduledTransactions(CONFIG)
        result = service.update_scheduled_transaction(budget_id, scheduled_transaction_id,
                                                      {"scheduled_transaction": st})
        logger.info("update_ynab_scheduled_transaction done id=%s", scheduled_transaction_id)
        return result

    @mcp.tool()
    def delete_ynab_scheduled_transaction(budget_id: str, scheduled_transaction_id: str) -> dict:
        """Delete a scheduled transaction by id (destructive).

        Args:
            budget_id: The YNAB budget UUID.
            scheduled_transaction_id: The scheduled transaction UUID to delete.
        """
        logger.info("Tool called: delete_ynab_scheduled_transaction id=%s", scheduled_transaction_id)
        service = ApiServiceYNABScheduledTransactions(CONFIG)
        result = service.delete_scheduled_transaction(budget_id, scheduled_transaction_id)
        logger.info("delete_ynab_scheduled_transaction done id=%s", scheduled_transaction_id)
        return result
