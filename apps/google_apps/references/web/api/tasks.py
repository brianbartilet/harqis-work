from __future__ import annotations

from typing import Optional, Dict, Any, List

from apps.google_apps.references.web.discovery import BaseGoogleDiscoveryService


class ApiServiceGoogleTasks(BaseGoogleDiscoveryService):
    """
    Google Tasks service using the discovery API.

    Wraps tasks.googleapis.com v1:
      - tasklists().list/get/insert/delete
      - tasks().list/get/insert/update/delete/clear

    Docs:
      https://developers.google.com/tasks/reference/rest

    Requires scope: https://www.googleapis.com/auth/tasks
    """

    SERVICE_NAME = "tasks"
    SERVICE_VERSION = "v1"

    def __init__(self, config, **kwargs) -> None:
        super().__init__(config, **kwargs)
        self._tasklists = self.service.tasklists()
        self._tasks = self.service.tasks()

    # ── Task Lists ────────────────────────────────────────────────────────

    def list_task_lists(self, max_results: int = 100) -> List[Dict[str, Any]]:
        """
        List all task lists for the authenticated user.

        Returns:
            List of TaskList dicts with id, title, updated.
        """
        result = self._tasklists.list(maxResults=max_results).execute()
        return result.get('items', [])

    def get_task_list(self, tasklist_id: str) -> Dict[str, Any]:
        """
        Get a specific task list by ID.

        Args:
            tasklist_id: Task list ID (use '@default' for the default list).

        Returns:
            TaskList dict with id, title, updated.
        """
        return self._tasklists.get(tasklist=tasklist_id).execute()

    def create_task_list(self, title: str) -> Dict[str, Any]:
        """
        Create a new task list.

        Args:
            title: Title of the new task list.

        Returns:
            Created TaskList dict.
        """
        return self._tasklists.insert(body={'title': title}).execute()

    def delete_task_list(self, tasklist_id: str) -> None:
        """
        Delete a task list and all its tasks.

        Args:
            tasklist_id: Task list ID.
        """
        self._tasklists.delete(tasklist=tasklist_id).execute()

    # ── Tasks ─────────────────────────────────────────────────────────────

    def list_tasks(self, tasklist_id: str = '@default',
                   show_completed: bool = False,
                   show_hidden: bool = False,
                   max_results: int = 100) -> List[Dict[str, Any]]:
        """
        List tasks in a task list.

        Args:
            tasklist_id:     Task list ID. '@default' uses the default list.
            show_completed:  Include completed tasks. Default False.
            show_hidden:     Include hidden tasks. Default False.
            max_results:     Max tasks to return. Default 100.

        Returns:
            List of Task dicts with id, title, status, due, notes, updated.
        """
        result = self._tasks.list(
            tasklist=tasklist_id,
            showCompleted=show_completed,
            showHidden=show_hidden,
            maxResults=max_results,
        ).execute()
        return result.get('items', [])

    def get_task(self, task_id: str, tasklist_id: str = '@default') -> Dict[str, Any]:
        """
        Get a specific task by ID.

        Args:
            task_id:     Task ID.
            tasklist_id: Task list ID. Default '@default'.

        Returns:
            Task dict with id, title, status, due, notes, updated.
        """
        return self._tasks.get(tasklist=tasklist_id, task=task_id).execute()

    def create_task(self, title: str, notes: str = None,
                    due: str = None,
                    tasklist_id: str = '@default') -> Dict[str, Any]:
        """
        Create a new task.

        Args:
            title:       Task title.
            notes:       Optional task notes/description.
            due:         Optional due date in RFC 3339 format (e.g. '2026-04-10T00:00:00.000Z').
            tasklist_id: Target task list. Default '@default'.

        Returns:
            Created Task dict.
        """
        body: Dict[str, Any] = {'title': title}
        if notes:
            body['notes'] = notes
        if due:
            body['due'] = due
        return self._tasks.insert(tasklist=tasklist_id, body=body).execute()

    def update_task(self, task_id: str, updates: Dict[str, Any],
                    tasklist_id: str = '@default') -> Dict[str, Any]:
        """
        Update a task's fields.

        Args:
            task_id:     Task ID.
            updates:     Dict of fields to update (title, notes, due, status).
            tasklist_id: Task list ID. Default '@default'.

        Returns:
            Updated Task dict.
        """
        existing = self.get_task(task_id, tasklist_id)
        existing.update(updates)
        return self._tasks.update(
            tasklist=tasklist_id, task=task_id, body=existing
        ).execute()

    def complete_task(self, task_id: str,
                      tasklist_id: str = '@default') -> Dict[str, Any]:
        """
        Mark a task as completed.

        Args:
            task_id:     Task ID.
            tasklist_id: Task list ID. Default '@default'.

        Returns:
            Updated Task dict with status='completed'.
        """
        return self.update_task(task_id, {'status': 'completed'}, tasklist_id)

    def delete_task(self, task_id: str,
                    tasklist_id: str = '@default') -> None:
        """
        Delete a task.

        Args:
            task_id:     Task ID.
            tasklist_id: Task list ID. Default '@default'.
        """
        self._tasks.delete(tasklist=tasklist_id, task=task_id).execute()

    def clear_completed_tasks(self, tasklist_id: str = '@default') -> None:
        """
        Clear all completed tasks from a task list.

        Args:
            tasklist_id: Task list ID. Default '@default'.
        """
        self._tasks.clear(tasklist=tasklist_id).execute()

    # ── Convenience ───────────────────────────────────────────────────────

    def list_all_tasks(self, show_completed: bool = False) -> List[Dict[str, Any]]:
        """
        List all tasks across all task lists for the authenticated user.

        Args:
            show_completed: Include completed tasks. Default False.

        Returns:
            Flat list of Task dicts, each with an added 'taskListTitle' field.
        """
        all_tasks: List[Dict[str, Any]] = []
        for task_list in self.list_task_lists():
            tasks = self.list_tasks(
                tasklist_id=task_list['id'],
                show_completed=show_completed,
            )
            for task in tasks:
                task['taskListTitle'] = task_list.get('title', '')
            all_tasks.extend(tasks)
        return all_tasks
