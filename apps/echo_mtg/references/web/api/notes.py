from apps.echo_mtg.references.web.base_api_service import BaseApiServiceAppEchoMtg

from core.web.services.core.decorators.deserializer import deserialized
from core.web.services.core.constants.http_headers import HttpHeaders
from core.web.services.core.constants.payload_type import PayloadType

from typing import List

class ApiServiceEchoMTGNotes(BaseApiServiceAppEchoMtg):

    def __init__(self, config, **kwargs):
        super(ApiServiceEchoMTGNotes, self).__init__(config, **kwargs)
        self.initialize()

    def initialize(self):
        self.request\
            .set_base_uri('notes')

    @deserialized(dict)
    def get_note(self, note_id: str):
        self.request.get() \
            .add_uri_parameter('note') \
            .add_query_string('id', note_id) \

        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def create_note(self, inventory_id: str, note: str, target_app: str = "inventory"):
        payload = {
            'target_id': inventory_id,
            'target_app': target_app,
            'note': note,
        }

        self.request.post() \
            .add_uri_parameter('create') \
            .add_json_payload(payload) \

        response = self.client.execute_request(self.request.build())
        if response.status_code == 404:
            raise Exception("Failed to create note: Inventory item not found or note already existing.")

        return response

    @deserialized(dict)
    def update_note(self, note_id: str, note: str):
        payload = {
            'note': note,
            'id': note_id,
        }

        self.request.post() \
            .add_uri_parameter('edit') \
            .add_json_payload(payload) \

        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def delete_note(self, note_id: str):
        payload = {
            'id': note_id,
        }

        self.request.post() \
            .add_uri_parameter('delete') \
            .add_json_payload(payload) \

        return self.client.execute_request(self.request.build())

