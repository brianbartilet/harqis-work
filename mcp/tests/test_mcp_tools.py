"""
Integration tests for the MCP tool layer.

Each test verifies that the underlying service call used by an MCP tool
returns a valid, non-empty response. Tests require valid credentials in
.env/apps.env and apps_config.yaml.
"""
import pytest
from hamcrest import assert_that, greater_than_or_equal_to, instance_of, is_not, none, not_none

# ── OANDA ──────────────────────────────────────────────────────────────────────

from apps.oanda.references.web.api.account import ApiServiceOandaAccount
from apps.oanda.references.web.api.open_trades import ApiServiceTrades
from apps.oanda.config import CONFIG as OANDA_CONFIG


@pytest.fixture()
def oanda_account_service():
    return ApiServiceOandaAccount(OANDA_CONFIG)


@pytest.fixture()
def oanda_trades_service():
    return ApiServiceTrades(OANDA_CONFIG)


@pytest.mark.smoke
def test_mcp_get_oanda_accounts(oanda_account_service):
    accounts = oanda_account_service.get_account_info()
    assert_that(len(accounts), greater_than_or_equal_to(1))


@pytest.mark.smoke
def test_mcp_get_oanda_account_details(oanda_account_service):
    accounts = oanda_account_service.get_account_info()
    account_id = accounts[0].id
    details = oanda_account_service.get_account_details(account_id)
    assert_that(details.balance, not_none())


# ── YNAB ───────────────────────────────────────────────────────────────────────

from apps.ynab.references.web.api.budgets import ApiServiceYNABBudgets
from apps.ynab.references.web.api.transactions import ApiServiceYNABTransactions
from apps.ynab.references.web.api.user import ApiServiceYNABUser
from apps.ynab.config import CONFIG as YNAB_CONFIG


@pytest.fixture()
def ynab_budget_service():
    return ApiServiceYNABBudgets(YNAB_CONFIG)


@pytest.fixture()
def ynab_transaction_service():
    return ApiServiceYNABTransactions(YNAB_CONFIG)


@pytest.mark.smoke
def test_mcp_get_ynab_budgets(ynab_budget_service):
    result = ynab_budget_service.get_budgets()
    budgets = result.get("budgets", [])
    assert_that(len(budgets), greater_than_or_equal_to(1))


@pytest.mark.smoke
def test_mcp_get_ynab_accounts(ynab_budget_service):
    budgets = ynab_budget_service.get_budgets().get("budgets", [])
    budget_id = budgets[0]["id"]
    result = ynab_budget_service.get_accounts(budget_id)
    accounts = result.get("accounts", [])
    assert_that(len(accounts), greater_than_or_equal_to(1))


@pytest.mark.smoke
def test_mcp_get_ynab_user():
    service = ApiServiceYNABUser(YNAB_CONFIG)
    result = service.get_user_info()
    assert_that(result, not_none())


# ── GOOGLE APPS ────────────────────────────────────────────────────────────────

from apps.google_apps.references.web.api.calendar import (
    ApiServiceGoogleCalendar,
    ApiServiceGoogleCalendarEvents,
    EventType,
)
from apps.google_apps.references.web.api.keep import ApiServiceGoogleKeepNotes
from apps.google_apps.references.web.api.gmail import ApiServiceGoogleGmail
from apps.google_apps.config import CONFIG as GOOGLE_CONFIG
from apps.apps_config import CONFIG_MANAGER

_KEEP_CONFIG = CONFIG_MANAGER.get("GOOGLE_KEEP")
_GMAIL_CONFIG = CONFIG_MANAGER.get("GOOGLE_GMAIL")


@pytest.fixture()
def google_calendar_service():
    return ApiServiceGoogleCalendar(GOOGLE_CONFIG)


@pytest.fixture()
def google_calendar_events_service():
    return ApiServiceGoogleCalendarEvents(GOOGLE_CONFIG)


@pytest.fixture()
def google_keep_service():
    return ApiServiceGoogleKeepNotes(_KEEP_CONFIG)


@pytest.fixture()
def google_gmail_service():
    return ApiServiceGoogleGmail(_GMAIL_CONFIG)


@pytest.mark.smoke
def test_mcp_get_google_calendar_holidays(google_calendar_service):
    holidays = google_calendar_service.get_holidays()
    assert_that(holidays, instance_of(list))


@pytest.mark.smoke
def test_mcp_get_google_calendar_events_today(google_calendar_events_service):
    events = google_calendar_events_service.get_all_events_today(event_type=EventType.ALL)
    assert_that(events, instance_of(list))


@pytest.mark.smoke
def test_mcp_list_google_keep_notes(google_keep_service):
    notes = google_keep_service.list_non_trashed_notes()
    assert_that(notes, instance_of(list))


@pytest.mark.smoke
def test_mcp_get_gmail_recent_emails(google_gmail_service):
    emails = google_gmail_service.get_recent_emails(max_results=10)
    assert_that(emails, instance_of(list))
    assert_that(len(emails), greater_than_or_equal_to(1))


@pytest.mark.smoke
def test_mcp_get_gmail_recent_emails_fields(google_gmail_service):
    emails = google_gmail_service.get_recent_emails(max_results=1)
    assert_that(len(emails), greater_than_or_equal_to(1))
    email = emails[0]
    assert_that(email.get("id"), not_none())
    assert_that(email.get("subject"), not_none())
    assert_that(email.get("from"), not_none())


@pytest.mark.smoke
def test_mcp_search_gmail_unread(google_gmail_service):
    emails = google_gmail_service.get_recent_emails(max_results=5, query="is:unread")
    assert_that(emails, instance_of(list))


# ── TCG MARKETPLACE ────────────────────────────────────────────────────────────

from apps.tcg_mp.references.web.api.product import ApiServiceTcgMpProducts
from apps.tcg_mp.references.web.api.order import ApiServiceTcgMpOrder
from apps.tcg_mp.references.web.api.view import ApiServiceTcgMpUserView
from apps.tcg_mp.references.dto.order import EnumTcgOrderStatus
from apps.tcg_mp.config import CONFIG as TCG_CONFIG


@pytest.fixture()
def tcg_product_service():
    return ApiServiceTcgMpProducts(TCG_CONFIG)


@pytest.fixture()
def tcg_order_service():
    return ApiServiceTcgMpOrder(TCG_CONFIG)


@pytest.fixture()
def tcg_view_service():
    return ApiServiceTcgMpUserView(TCG_CONFIG)


@pytest.mark.smoke
def test_mcp_search_tcg_card(tcg_product_service):
    results = tcg_product_service.search_card("Black Lotus", page=1, items=5)
    assert_that(results, instance_of(list))


@pytest.mark.smoke
def test_mcp_get_tcg_orders(tcg_order_service):
    orders = tcg_order_service.get_orders(by_status=EnumTcgOrderStatus.ALL)
    assert_that(orders, instance_of(list))


@pytest.mark.smoke
def test_mcp_get_tcg_listings(tcg_view_service):
    listings = tcg_view_service.get_listings()
    assert_that(listings, instance_of(list))


# ── ECHO MTG ───────────────────────────────────────────────────────────────────

from apps.echo_mtg.references.web.api.inventory import ApiServiceEchoMTGInventory
from apps.echo_mtg.config import CONFIG as ECHO_CONFIG


@pytest.fixture()
def echo_mtg_inventory_service():
    return ApiServiceEchoMTGInventory(ECHO_CONFIG)


@pytest.mark.smoke
def test_mcp_get_echo_mtg_portfolio_stats(echo_mtg_inventory_service):
    stats = echo_mtg_inventory_service.get_quick_stats()
    assert_that(stats, not_none())


@pytest.mark.smoke
def test_mcp_get_echo_mtg_collection(echo_mtg_inventory_service):
    items = echo_mtg_inventory_service.get_collection(start=0, limit=10)
    assert_that(items, instance_of(list))


# ── SCRYFALL ───────────────────────────────────────────────────────────────────

from apps.scryfall.references.web.api.cards import ApiServiceScryfallCards
from apps.scryfall.references.web.api.bulk import ApiServiceScryfallBulkData
from apps.scryfall.config import CONFIG as SCRYFALL_CONFIG

# Known stable Scryfall UUID for "Black Lotus" (Limited Edition Alpha)
_BLACK_LOTUS_GUID = "b0faa7f2-b547-42c4-a810-839da50dadfe"


@pytest.fixture()
def scryfall_cards_service():
    return ApiServiceScryfallCards(SCRYFALL_CONFIG)


@pytest.fixture()
def scryfall_bulk_service():
    return ApiServiceScryfallBulkData(SCRYFALL_CONFIG)


@pytest.mark.smoke
def test_mcp_get_scryfall_card(scryfall_cards_service):
    card = scryfall_cards_service.get_card_metadata(_BLACK_LOTUS_GUID)
    assert_that(card, not_none())


@pytest.mark.smoke
def test_mcp_get_scryfall_bulk_data_info(scryfall_bulk_service):
    data = scryfall_bulk_service.get_card_data_bulk(bulk_data_type="all-cards")
    assert_that(data, not_none())
