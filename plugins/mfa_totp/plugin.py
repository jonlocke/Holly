from typing import Any


class Plugin:
    id = "mfa_totp"
    version = "0.1.0"
    timeout_seconds = 1.0

    def __init__(self):
        self.app_context: dict[str, Any] | None = None
        self.commands = {
            "/mfa-setup": "Planned: enroll TOTP secret",
            "/mfa-verify": "Planned: verify TOTP code",
            "/mfa-recovery": "Planned: consume a recovery code",
        }

    def on_load(self, app_context):
        self.app_context = app_context

    def on_unload(self):
        self.app_context = None

    def on_command(self, command, args, context):
        return {
            "type": "command_response",
            "command": command,
            "content": "mfa_totp is a scaffold plugin. Implement TOTP and recovery-code flow next.",
        }
