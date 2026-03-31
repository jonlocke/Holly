from __future__ import annotations

import logging
import subprocess
from typing import Any


logger = logging.getLogger(__name__)


class Plugin:
    id = "ssh"
    version = "0.1.0"
    timeout_seconds = 20.0

    def __init__(self):
        self.app_context: dict[str, Any] | None = None
        self.commands = {
            "/ssh": "Run a remote command over SSH. Usage: /ssh [--host=<host>] <command>",
        }
        self.tools = {
            "ssh.run_command": {
                "description": "Run a command over SSH on a configured host.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "description": "The remote shell command to execute.",
                        },
                        "host": {
                            "type": "string",
                            "description": "Optional SSH host override. Defaults to the configured host.",
                        },
                    },
                    "required": ["command"],
                },
            }
        }
        self._default_host = "holly-voice"
        self._connect_timeout_seconds = 5
        self._command_timeout_seconds = 15

    def on_load(self, app_context):
        self.app_context = app_context
        config = ((app_context or {}).get("config", {}).get("plugins", {}).get("ssh", {}))
        self._default_host = str(config.get("default_host", "holly-voice")).strip() or "holly-voice"
        self._connect_timeout_seconds = max(1, int(config.get("connect_timeout_seconds", 5)))
        self._command_timeout_seconds = max(1, int(config.get("command_timeout_seconds", 15)))

    def on_unload(self):
        self.app_context = None

    def on_command(self, command, args, context):
        host, remote_command = self._parse_command_args(args)
        if not remote_command:
            return {
                "type": "command_response",
                "command": command,
                "content": "Usage: /ssh [--host=<host>] <command>",
            }

        result = self._run_ssh_command(host, remote_command, context, source="command")
        return {
            "type": "command_response",
            "command": command,
            "content": result["content"],
            "data": result,
        }

    def call_tool(self, tool_name, arguments, context):
        if tool_name != "ssh.run_command":
            raise ValueError(f"Unsupported SSH tool '{tool_name}'.")

        remote_command = str((arguments or {}).get("command") or "").strip()
        if not remote_command:
            raise ValueError("The SSH tool requires a command.")

        host = str((arguments or {}).get("host") or "").strip() or self._default_host
        result = self._run_ssh_command(host, remote_command, context, source="tool")
        return {
            "ok": True,
            "tool_name": tool_name,
            "content": result["content"],
            "data": result,
        }

    def _parse_command_args(self, args: list[str]) -> tuple[str, str]:
        host = self._default_host
        remaining = list(args or [])
        if remaining and str(remaining[0]).startswith("--host="):
            host = str(remaining.pop(0)).split("=", 1)[1].strip() or self._default_host
        remote_command = " ".join(str(arg) for arg in remaining).strip()
        return host, remote_command

    def _run_ssh_command(
        self,
        host: str,
        remote_command: str,
        context: dict[str, Any] | None,
        *,
        source: str,
    ) -> dict[str, Any]:
        logger.info(
            "SSH plugin invoked via %s host=%r command=%r session_id=%s user=%s",
            source,
            host,
            remote_command,
            str((context or {}).get("session_id") or "unknown"),
            str((context or {}).get("username") or (context or {}).get("user_id") or "anonymous"),
        )

        ssh_command = [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=accept-new",
            "-o",
            f"ConnectTimeout={self._connect_timeout_seconds}",
            host,
            remote_command,
        ]
        completed = subprocess.run(  # nosec B603 - command is executed without a shell and arguments are passed as a list.
            ssh_command,
            capture_output=True,
            text=True,
            timeout=self._command_timeout_seconds,
            check=False,
        )

        stdout = (completed.stdout or "").strip()
        stderr = (completed.stderr or "").strip()
        if completed.returncode == 0:
            content = stdout or f"SSH command completed successfully on {host}."
        else:
            details = stderr or stdout or f"exit code {completed.returncode}"
            content = f"SSH command failed on {host}: {details}"

        return {
            "ok": completed.returncode == 0,
            "host": host,
            "command": remote_command,
            "stdout": stdout,
            "stderr": stderr,
            "returncode": int(completed.returncode),
            "content": content,
        }
