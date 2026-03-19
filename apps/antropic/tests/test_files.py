import os
import tempfile
import pytest

from hamcrest import assert_that, not_none, instance_of, greater_than_or_equal_to

from apps.antropic.config import CONFIG
from apps.antropic.references.dto.file import DtoAnthropicFile
from apps.antropic.references.web.api.files import ApiServiceAnthropicFiles


@pytest.fixture()
def given_service():
    return ApiServiceAnthropicFiles(CONFIG)


@pytest.fixture()
def given_temp_text_file():
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        f.write("Hello from harqis-work test.")
        path = f.name
    yield path
    if os.path.exists(path):
        os.remove(path)


@pytest.mark.smoke
def test_files_service_initializes(given_service):
    assert_that(given_service.base_client, not_none())


@pytest.mark.sanity
def test_upload_file_returns_dto(given_service, given_temp_text_file):
    result = given_service.upload_file(given_temp_text_file, mime_type='text/plain')

    assert_that(result, instance_of(DtoAnthropicFile))
    assert_that(result.id, not_none())
    assert_that(result.filename, not_none())

    # cleanup
    given_service.delete_file(result.id)


@pytest.mark.sanity
def test_list_files_returns_list(given_service):
    result = given_service.list_files()

    assert_that(result, not_none())
    assert_that(isinstance(result, list), True)


@pytest.mark.sanity
def test_upload_and_delete_file(given_service, given_temp_text_file):
    uploaded = given_service.upload_file(given_temp_text_file, mime_type='text/plain')
    assert_that(uploaded.id, not_none())

    deleted = given_service.delete_file(uploaded.id)
    assert_that(deleted, not_none())


@pytest.mark.sanity
def test_retrieve_file_metadata(given_service, given_temp_text_file):
    uploaded = given_service.upload_file(given_temp_text_file, mime_type='text/plain')

    try:
        metadata = given_service.retrieve_file_metadata(uploaded.id)
        assert_that(metadata, instance_of(DtoAnthropicFile))
        assert_that(metadata.id, not_none())
    finally:
        given_service.delete_file(uploaded.id)
