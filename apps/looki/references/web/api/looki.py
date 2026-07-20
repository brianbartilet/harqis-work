from __future__ import annotations

from typing import Optional
from urllib.parse import quote

from core.web.services.core.decorators.deserializer import deserialized

from apps.looki.references.web.base_api_service import BaseApiServiceLooki


class ApiServiceLooki(BaseApiServiceLooki):
    """The seven read-only endpoints exposed by the Looki developer API."""

    @deserialized(dict)
    def get_me(self) -> dict:
        self.request.get().set_base_uri("me")
        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def list_moments(self, on_date: str) -> dict:
        self.request.get().set_base_uri("moments")
        self.request.add_query_string("on_date", on_date)
        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def search_moments(
        self,
        query: str,
        *,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        self.request.get().set_base_uri("moments/search")
        for key, value in {
            "query": query,
            "start_date": start_date,
            "end_date": end_date,
            "page": page,
            "page_size": page_size,
        }.items():
            if value is not None:
                self.request.add_query_string(key, value)
        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def get_calendar(self, start_date: str, end_date: str) -> dict:
        self.request.get().set_base_uri("moments/calendar")
        self.request.add_query_string("start_date", start_date)
        self.request.add_query_string("end_date", end_date)
        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def get_moment(self, moment_id: str) -> dict:
        safe_id = quote(str(moment_id), safe="")
        self.request.get().set_base_uri(f"moments/{safe_id}")
        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def list_moment_files(
        self,
        moment_id: str,
        *,
        highlight: Optional[bool] = None,
        cursor_id: Optional[str] = None,
        limit: int = 20,
    ) -> dict:
        safe_id = quote(str(moment_id), safe="")
        self.request.get().set_base_uri(f"moments/{safe_id}/files")
        for key, value in {
            "highlight": highlight,
            "cursor_id": cursor_id,
            "limit": limit,
        }.items():
            if value is not None:
                self.request.add_query_string(key, value)
        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def list_for_you(
        self,
        *,
        group: Optional[str] = None,
        liked: Optional[bool] = None,
        recorded_from: Optional[str] = None,
        recorded_to: Optional[str] = None,
        cursor_id: Optional[str] = None,
        limit: int = 20,
        order_by: Optional[str] = None,
    ) -> dict:
        self.request.get().set_base_uri("for_you/items")
        for key, value in {
            "group": group,
            "liked": liked,
            "recorded_from": recorded_from,
            "recorded_to": recorded_to,
            "cursor_id": cursor_id,
            "limit": limit,
            "order_by": order_by,
        }.items():
            if value is not None:
                self.request.add_query_string(key, value)
        return self.client.execute_request(self.request.build())
