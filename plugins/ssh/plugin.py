from __future__ import annotations

import logging
import os
from pathlib import Path
import subprocess
from typing import Any


logger = logging.getLogger(__name__)


class Plugin:
    id = "ssh"
    version = "0.2.0"
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
        self._key_path = Path("/data/ssh/id_ed25519")

    def on_load(self, app_context):
        self.app_context = app_context
        config = ((app_context or {}).get("config", {}).get("plugins", {}).get("ssh", {}))
        self._default_host = str(config.get("default_host", "holly-voice")).strip() or "holly-voice"
        self._connect_timeout_seconds = max(1, int(config.get("connect_timeout_seconds", 5)))
        self._command_timeout_seconds = max(1, int(config.get("command_timeout_seconds", 15)))
        configured_key_path = str(config.get("key_path", "/data/ssh/id_ed25519")).strip() or "/data/ssh/id_ed25519"
        self._key_path = Path(configured_key_path)
        self._ensure_keypair()

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
        self._validate_tool_arguments(host, remote_command)
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

    def _validate_tool_arguments(self, host: str, remote_command: str) -> None:
        normalized_host = self._normalize_host(host).lower()
        normalized_command = str(remote_command or "").strip().lower()
        if not normalized_command:
            raise ValueError("The SSH tool requires a command.")

        invalid_commands = {
            "ssh",
            "ssh.run_command",
            "run_ssh_command",
            "tool",
            "command",
            "hostname value",
        }
        if normalized_command in invalid_commands:
            raise ValueError("The SSH tool requires the actual remote command to run, not the tool name or a placeholder.")

        if normalized_command == normalized_host or normalized_command == normalized_host.split("@", 1)[-1]:
            raise ValueError("The SSH tool requires a remote command, not just the host.")

        if normalized_command.startswith("holly@") and " " not in normalized_command:
            raise ValueError("The SSH tool requires a remote command, not an SSH destination.")

        if normalized_command.startswith("ssh ") or normalized_command.startswith("ssh\t"):
            raise ValueError("The SSH tool requires the remote command only, without wrapping it in another ssh command.")

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
            "-i",
            str(self._key_path),
            "-o",
            "BatchMode=yes",
            "-o",
            "IdentitiesOnly=yes",
            "-o",
            "StrictHostKeyChecking=accept-new",
            "-o",
            f"ConnectTimeout={self._connect_timeout_seconds}",
            self._normalize_host(host),
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

    def _ensure_keypair(self) -> None:
        private_key_path = self._key_path
        public_key_path = Path(f"{self._key_path}.pub")
        private_key_path.parent.mkdir(parents=True, exist_ok=True)

        if private_key_path.exists() and public_key_path.exists():
            self._chmod_keypair(private_key_path, public_key_path)
            logger.info("SSH plugin reusing keypair at %s", private_key_path)
            return

        if private_key_path.exists():
            private_key_path.unlink()
        if public_key_path.exists():
            public_key_path.unlink()

        comment = f"holly@{os.uname().nodename}"
        keygen_command = [
            "ssh-keygen",
            "-q",
            "-t",
            "ed25519",
            "-N",
            "",
            "-C",
            comment,
            "-f",
            str(private_key_path),
        ]
        subprocess.run(  # nosec B603 - command is executed without a shell and arguments are passed as a list.
            keygen_command,
            capture_output=True,
            text=True,
            timeout=self._command_timeout_seconds,
            check=True,
        )
        self._chmod_keypair(private_key_path, public_key_path)
        logger.info("SSH plugin generated new keypair at %s", private_key_path)

    def _chmod_keypair(self, private_key_path: Path, public_key_path: Path) -> None:
        private_key_path.chmod(0o600)
        if public_key_path.exists():
            public_key_path.chmod(0o644)

    def _normalize_host(self, host: str) -> str:
        normalized = str(host or "").strip()
        if not normalized:
            return f"holly@{self._default_host}"
        if "@" in normalized:
            return normalized
        return f"holly@{normalized}"
