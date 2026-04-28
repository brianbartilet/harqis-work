import pytest
from hamcrest import assert_that, not_none, instance_of, greater_than_or_equal_to

from apps.airtable.references.web.api.bases import ApiServiceAirtableBases
from apps.airtable.references.web.api.tables import ApiServiceAirtableTables
from apps.airtable.references.web.api.records import ApiServiceAirtableRecords
from apps.airtable.references.dto.bases import DtoAirtableBase, DtoAirtableUser
from apps.airtable.references.dto.tables import DtoAirtableTable
from apps.airtable.references.dto.records import DtoAirtableRecordsPage
from apps.airtable.config import CONFIG


@pytest.fixture()
def bases_svc():
    return ApiServiceAirtableBases(CONFIG)


@pytest.fixture()
def tables_svc():
    return ApiServiceAirtableTables(CONFIG)


@pytest.fixture()
def records_svc():
    return ApiServiceAirtableRecords(CONFIG)


@pytest.mark.smoke
def test_whoami(bases_svc):
    result = bases_svc.whoami()
    assert_that(result, instance_of(DtoAirtableUser))
    assert_that(result.id, not_none())


@pytest.mark.smoke
def test_list_bases(bases_svc):
    result = bases_svc.list_bases()
    assert_that(result, instance_of(list))
    assert_that(len(result), greater_than_or_equal_to(0))
    if result:
        assert_that(result[0], instance_of(DtoAirtableBase))
        assert_that(result[0].id, not_none())


@pytest.mark.sanity
def test_list_tables(bases_svc, tables_svc):
    bases = bases_svc.list_bases()
    if not bases:
        pytest.skip("No bases available on this PAT")
    result = tables_svc.list_tables(base_id=bases[0].id)
    assert_that(result, instance_of(list))
    if result:
        assert_that(result[0], instance_of(DtoAirtableTable))
        assert_that(result[0].id, not_none())


@pytest.mark.sanity
def test_list_records(bases_svc, tables_svc, records_svc):
    bases = bases_svc.list_bases()
    if not bases:
        pytest.skip("No bases available on this PAT")
    tables = tables_svc.list_tables(base_id=bases[0].id)
    if not tables:
        pytest.skip("First base has no tables")
    page = records_svc.list_records(
        base_id=bases[0].id, table=tables[0].id, page_size=3
    )
    assert_that(page, instance_of(DtoAirtableRecordsPage))
    assert_that(page.records, not_none())
