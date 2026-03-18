from typing import Any


class Plugin:
    id = "acl_rbac"
    version = "0.1.0"
    timeout_seconds = 1.0

    def __init__(self):
        self.app_context: dict[str, Any] | None = None
        self.commands = {
            "/policy-status": "Planned: show active authorization policy summary",
        }

    def on_load(self, app_context):
        self.app_context = app_context

    def on_unload(self):
        self.app_context = None

    def on_command(self, command, args, context):
        return {
            "type": "command_response",
            "command": command,
            "content": "acl_rbac is a scaffold plugin. Implement role and command policy evaluation next.",
        }
