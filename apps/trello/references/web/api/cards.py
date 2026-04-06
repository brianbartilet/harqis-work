from typing import List, Optional

from apps.trello.references.web.base_api_service import BaseApiServiceTrello
from core.web.services.core.decorators.deserializer import deserialized


class ApiServiceTrelloCards(BaseApiServiceTrello):
    """
    Trello REST API — card operations.

    Methods:
        get_card()          → Single card by ID
        get_list_cards()    → All cards in a list
        create_card()       → Create a card in a list
        update_card()       → Update card fields
        archive_card()      → Close (archive) a card
        move_card()         → Move a card to a different list
    """

    def __init__(self, config, **kwargs):
        super(ApiServiceTrelloCards, self).__init__(config, **kwargs)

    @deserialized(dict)
    def get_card(self, card_id: str):
        """
        Get a single card by ID.

        Args:
            card_id: The card's 24-char Trello ID.
        """
        self.request.get() \
            .add_uri_parameter('cards') \
            .add_uri_parameter(card_id)

        return self.client.execute_request(self.request.build())

    @deserialized(List[dict])
    def get_list_cards(self, list_id: str, filter: str = 'open'):
        """
        Get all cards in a list.

        Args:
            list_id: The list's 24-char Trello ID.
            filter:  'all', 'open' (default), or 'closed'.
        """
        self.request.get() \
            .add_uri_parameter('lists') \
            .add_uri_parameter(list_id) \
            .add_uri_parameter('cards') \
            .add_query_string('filter', filter)

        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def create_card(self, list_id: str, name: str, desc: str = None, due: str = None,
                    id_members: List[str] = None, id_labels: List[str] = None):
        """
        Create a new card in a list.

        Args:
            list_id:    Target list ID (required).
            name:       Card name (required).
            desc:       Optional card description.
            due:        Optional due date (ISO 8601 string).
            id_members: Optional list of member IDs to assign.
            id_labels:  Optional list of label IDs to apply.
        """
        payload = {'idList': list_id, 'name': name}
        if desc:
            payload['desc'] = desc
        if due:
            payload['due'] = due
        if id_members:
            payload['idMembers'] = ','.join(id_members)
        if id_labels:
            payload['idLabels'] = ','.join(id_labels)

        self.request.post() \
            .add_uri_parameter('cards') \
            .add_json_payload(payload)

        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def update_card(self, card_id: str, name: str = None, desc: str = None,
                    due: str = None, due_complete: bool = None,
                    id_list: str = None, closed: bool = None):
        """
        Update fields on an existing card.

        Args:
            card_id:      The card's 24-char Trello ID.
            name:         New card name.
            desc:         New card description.
            due:          Due date (ISO 8601 string). Pass None to clear.
            due_complete: Mark due date as complete/incomplete.
            id_list:      Move card to this list ID.
            closed:       Archive (True) or unarchive (False) the card.
        """
        payload = {}
        if name is not None:
            payload['name'] = name
        if desc is not None:
            payload['desc'] = desc
        if due is not None:
            payload['due'] = due
        if due_complete is not None:
            payload['dueComplete'] = due_complete
        if id_list is not None:
            payload['idList'] = id_list
        if closed is not None:
            payload['closed'] = closed

        self.request.put() \
            .add_uri_parameter('cards') \
            .add_uri_parameter(card_id) \
            .add_json_payload(payload)

        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def archive_card(self, card_id: str):
        """
        Archive a card (set closed=True).

        Args:
            card_id: The card's 24-char Trello ID.
        """
        self.request.put() \
            .add_uri_parameter('cards') \
            .add_uri_parameter(card_id) \
            .add_json_payload({'closed': True})

        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def move_card(self, card_id: str, list_id: str):
        """
        Move a card to a different list.

        Args:
            card_id: The card's 24-char Trello ID.
            list_id: Target list ID.
        """
        self.request.put() \
            .add_uri_parameter('cards') \
            .add_uri_parameter(card_id) \
            .add_json_payload({'idList': list_id})

        return self.client.execute_request(self.request.build())
