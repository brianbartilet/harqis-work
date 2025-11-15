import pytest

from hamcrest import greater_than_or_equal_to

from apps.echo_mtg.references.web.api.notes import ApiServiceEchoMTGNotes
from apps.echo_mtg.references.web.api.inventory import ApiServiceEchoMTGInventory
from apps.echo_mtg.config import CONFIG
from core.utilities.data.qlist import QList

@pytest.fixture()
def given_account():
    given_service_notes = ApiServiceEchoMTGNotes(CONFIG)
    given_service_inventory = ApiServiceEchoMTGInventory(CONFIG)
    inventory_data = given_service_inventory.get_collection(start=1, limit=1)
    target_inventory_item = inventory_data[0]['inventory_id']
    return given_service_notes, target_inventory_item


@pytest.mark.skip(reason="sanity check only")
def test_note_flow(given_account):
    given_service_notes, target = given_account
    then = given_service_notes.verify.common
    when_create = given_service_notes.create_note(target, "This is a test note.")
    then.assert_that(when_create.data['message'], "note created successfully")
    when_get_note = given_service_notes.get_note(when_create.data['note_id'])
    then.assert_that(when_get_note.data['message'], "note fetched")

    when_update = given_service_notes.update_note(when_get_note.data['note']['id'], "This is a test note updated.")
    then.assert_that(when_update.data['message'], "note updated successfully")

    when_delete = given_service_notes.delete_note(when_get_note.data['note']['id'])
    then.assert_that(when_delete.data['message'], "note deleted successfully")






