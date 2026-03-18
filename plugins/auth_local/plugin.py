from typing import Any


class Plugin:
    id = "auth_local"
    version = "0.1.0"
    timeout_seconds = 1.0

    def __init__(self):
        self.app_context: dict[str, Any] | None = None
        self.commands = {
            "/login": "Planned: authenticate local user",
            "/logout": "Planned: clear authenticated session",
            "/whoami": "Planned: show current authenticated user",
        }

    def on_load(self, app_context):
        self.app_context = app_context

    def on_unload(self):
        self.app_context = None

    def on_command(self, command, args, context):
        return {
            "type": "command_response",
            "command": command,
            "content": "auth_local is a scaffold plugin. Implement username/password flow next.",
        }
