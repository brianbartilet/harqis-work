from typing import List

from apps.orgo.references.web.base_api_service import BaseApiServiceOrgo
from core.web.services.core.decorators.deserializer import deserialized


class ApiServiceOrgoWorkspaces(BaseApiServiceOrgo):
    """
    Orgo AI API — workspace management.

    Methods:
        list_workspaces()       → List all workspaces
        get_workspace(id)       → Get workspace details
        create_workspace(name)  → Create a new workspace
        delete_workspace(id)    → Delete workspace and all its computers
    """

    def __init__(self, config, **kwargs):
        super(ApiServiceOrgoWorkspaces, self).__init__(config, **kwargs)

    @deserialized(List[dict], child='workspaces')
    def list_workspaces(self):
        """List all workspaces in the account."""
        self.request.get().add_uri_parameter('workspaces')
        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def get_workspace(self, workspace_id: str):
        """
        Get a workspace by ID.

        Args:
            workspace_id: UUID of the workspace.
        """
        self.request.get() \
            .add_uri_parameter('workspaces') \
            .add_uri_parameter(workspace_id)
        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def create_workspace(self, name: str):
        """
        Create a new workspace.

        Args:
            name: Workspace name — 1–64 chars, alphanumeric + hyphens/underscores.
        """
        self.request.post() \
            .add_uri_parameter('workspaces') \
            .add_json_payload({'name': name})
        return self.client.execute_request(self.request.build())

    def delete_workspace(self, workspace_id: str):
        """
        Delete a workspace and all its computers.

        Args:
            workspace_id: UUID of the workspace to delete.
        """
        self.request.delete() \
            .add_uri_parameter('workspaces') \
            .add_uri_parameter(workspace_id)
        return self.client.execute_request(self.request.build())
