from typing import Optional, List

from apps.orgo.references.web.base_api_service import BaseApiServiceOrgo
from core.web.services.core.decorators.deserializer import deserialized


class ApiServiceOrgoComputers(BaseApiServiceOrgo):
    """
    Orgo AI API — computer lifecycle and desktop interaction.

    Computers are cloud-hosted Linux VMs that AI agents can control
    autonomously: screenshot, click, type, run commands, etc.

    Methods:
        create_computer()   → Provision a new VM
        get_computer()      → Get computer status and details
        delete_computer()   → Terminate a computer
        start()             → Start a stopped computer
        stop()              → Stop a running computer
        restart()           → Restart a computer
        get_vnc_password()  → Get VNC password for WebSocket access
        screenshot()        → Capture current screen as base64 PNG
        click()             → Mouse click at coordinates
        double_click()      → Double click at coordinates
        right_click()       → Right click at coordinates
        type_text()         → Type a string of text
        key()               → Send a key or key combo
        scroll()            → Scroll the mouse wheel
        drag()              → Click-drag between two points
        bash()              → Execute a shell command
        wait()              → Pause execution on the computer
    """

    def __init__(self, config, **kwargs):
        super(ApiServiceOrgoComputers, self).__init__(config, **kwargs)

    # ── Lifecycle ──────────────────────────────────────────────────────────

    @deserialized(dict)
    def create_computer(self, workspace_id: str, name: str,
                        ram: int = 4, cpu: int = 2, gpu: str = 'none',
                        resolution: str = '1280x720x24',
                        auto_stop_minutes: Optional[int] = None):
        """
        Provision a new cloud computer.

        Args:
            workspace_id:       UUID of the workspace.
            name:               Unique name within the workspace.
            ram:                RAM in GB — 4, 8, 16, 32, or 64. Default 4.
            cpu:                CPU cores — 2, 4, 8, or 16. Default 2.
            gpu:                GPU type — 'none', 'a10', 'l40s', 'a100-40gb', 'a100-80gb'. Default 'none'.
            resolution:         Screen resolution — 'WxHxD'. Default '1280x720x24'.
            auto_stop_minutes:  Auto-stop after N minutes of inactivity. 0 or None to disable.

        Returns:
            Dict with id, name, workspace_id, os, ram, cpu, gpu, resolution, status, url, created_at.
        """
        payload = {
            'workspace_id': workspace_id,
            'name': name,
            'ram': ram,
            'cpu': cpu,
            'gpu': gpu,
            'resolution': resolution,
        }
        if auto_stop_minutes is not None:
            payload['auto_stop_minutes'] = auto_stop_minutes

        self.request.post() \
            .add_uri_parameter('computers') \
            .add_json_payload(payload)
        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def get_computer(self, computer_id: str):
        """
        Get details and current status for a computer.

        Args:
            computer_id: Computer ID string.

        Returns:
            Dict with status: 'starting'|'running'|'stopping'|'stopped'|'suspended'|'error'.
        """
        self.request.get() \
            .add_uri_parameter('computers') \
            .add_uri_parameter(computer_id)
        return self.client.execute_request(self.request.build())

    def delete_computer(self, computer_id: str):
        """
        Terminate and delete a computer.

        Args:
            computer_id: Computer ID string.
        """
        self.request.delete() \
            .add_uri_parameter('computers') \
            .add_uri_parameter(computer_id)
        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def start(self, computer_id: str):
        """Start a stopped computer."""
        self.request.post() \
            .add_uri_parameter('computers') \
            .add_uri_parameter(computer_id) \
            .add_uri_parameter('start')
        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def stop(self, computer_id: str):
        """Stop a running computer."""
        self.request.post() \
            .add_uri_parameter('computers') \
            .add_uri_parameter(computer_id) \
            .add_uri_parameter('stop')
        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def restart(self, computer_id: str):
        """Restart a computer."""
        self.request.post() \
            .add_uri_parameter('computers') \
            .add_uri_parameter(computer_id) \
            .add_uri_parameter('restart')
        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def get_vnc_password(self, computer_id: str):
        """
        Get the VNC password needed for WebSocket terminal/audio/events access.

        Returns:
            Dict with 'password' key. Use as token in wss://{computer_id}.orgo.dev/terminal?token=...
        """
        self.request.get() \
            .add_uri_parameter('computers') \
            .add_uri_parameter(computer_id) \
            .add_uri_parameter('vnc-password')
        return self.client.execute_request(self.request.build())

    # ── Desktop Actions ─────────────────────────────────────────────────────

    @deserialized(dict)
    def screenshot(self, computer_id: str):
        """
        Capture the current screen.

        Returns:
            Dict with base64-encoded PNG image data.
        """
        self.request.get() \
            .add_uri_parameter('computers') \
            .add_uri_parameter(computer_id) \
            .add_uri_parameter('screenshot')
        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def click(self, computer_id: str, x: int, y: int,
              button: str = 'left', double: bool = False):
        """
        Click at screen coordinates.

        Args:
            computer_id: Computer ID.
            x:           Horizontal position in pixels.
            y:           Vertical position in pixels.
            button:      'left' or 'right'. Default 'left'.
            double:      True for double-click. Default False.
        """
        self.request.post() \
            .add_uri_parameter('computers') \
            .add_uri_parameter(computer_id) \
            .add_uri_parameter('click') \
            .add_json_payload({'x': x, 'y': y, 'button': button, 'double': double})
        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def drag(self, computer_id: str,
             start_x: int, start_y: int, end_x: int, end_y: int,
             button: str = 'left', duration: float = 0.5):
        """
        Click-drag from one point to another.

        Args:
            computer_id: Computer ID.
            start_x/y:   Start coordinates.
            end_x/y:     End coordinates.
            button:      Mouse button to hold during drag. Default 'left'.
            duration:    Drag duration in seconds. Default 0.5.
        """
        payload = {
            'startX': start_x, 'startY': start_y,
            'endX': end_x, 'endY': end_y,
            'button': button, 'duration': duration,
        }
        self.request.post() \
            .add_uri_parameter('computers') \
            .add_uri_parameter(computer_id) \
            .add_uri_parameter('drag') \
            .add_json_payload(payload)
        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def type_text(self, computer_id: str, text: str):
        """
        Type a string of text on the computer.

        Args:
            computer_id: Computer ID.
            text:        String to type.
        """
        self.request.post() \
            .add_uri_parameter('computers') \
            .add_uri_parameter(computer_id) \
            .add_uri_parameter('type') \
            .add_json_payload({'text': text})
        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def key(self, computer_id: str, key: str):
        """
        Send a key press or key combination.

        Args:
            computer_id: Computer ID.
            key:         Key name or combo, e.g. 'Enter', 'Escape', 'ctrl+c', 'alt+Tab', 'F5'.
        """
        self.request.post() \
            .add_uri_parameter('computers') \
            .add_uri_parameter(computer_id) \
            .add_uri_parameter('key') \
            .add_json_payload({'key': key})
        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def scroll(self, computer_id: str, direction: str, amount: int = 3):
        """
        Scroll the mouse wheel.

        Args:
            computer_id: Computer ID.
            direction:   'up' or 'down'.
            amount:      Number of scroll ticks. Default 3.
        """
        self.request.post() \
            .add_uri_parameter('computers') \
            .add_uri_parameter(computer_id) \
            .add_uri_parameter('scroll') \
            .add_json_payload({'direction': direction, 'amount': amount})
        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def bash(self, computer_id: str, command: str):
        """
        Execute a shell command on the computer.

        Args:
            computer_id: Computer ID.
            command:     Shell command to run.

        Returns:
            Dict with 'output' (stdout/stderr) and 'success' (bool).
        """
        self.request.post() \
            .add_uri_parameter('computers') \
            .add_uri_parameter(computer_id) \
            .add_uri_parameter('bash') \
            .add_json_payload({'command': command})
        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def wait(self, computer_id: str, duration: float):
        """
        Pause execution on the computer.

        Args:
            computer_id: Computer ID.
            duration:    Seconds to wait. Maximum 60.
        """
        self.request.post() \
            .add_uri_parameter('computers') \
            .add_uri_parameter(computer_id) \
            .add_uri_parameter('wait') \
            .add_json_payload({'duration': duration})
        return self.client.execute_request(self.request.build())
