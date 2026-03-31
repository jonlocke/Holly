import importlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from plugin_system import PLUGIN_API_VERSION, PluginManager


class PluginManagerTests(unittest.TestCase):
    def test_manager_loads_manifest_driven_plugin_and_registers_command(self):
        manager = PluginManager(
            Path(__file__).resolve().parents[1] / "plugins",
            {"config": {"plugins": {"weather": {"provider": "open-meteo"}}}},
            trusted_plugins={"weather"},
        )

        loaded = manager.load_all_enabled()

        self.assertEqual(loaded, ["weather"])
        self.assertEqual(manager.command_registry["/weather"], "weather")
        self.assertEqual(manager.tool_registry["weather.get_current_weather"], "weather")

    def test_manager_rejects_incompatible_plugin_api_version(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            plugin_dir = root / "broken"
            plugin_dir.mkdir(parents=True)
            (plugin_dir / "manifest.json").write_text(
                """
                {
                  "id": "broken",
                  "name": "Broken",
                  "version": "0.0.1",
                  "plugin_api_version": "999.0",
                  "entrypoint": "plugins.weather.plugin:Plugin",
                  "description": "bad api",
                  "required_config_keys": [],
                  "permissions": ["messaging"],
                  "enabled": true
                }
                """,
                encoding="utf-8",
            )
            manager = PluginManager(root, {"config": {"plugins": {}}})

            discovered = manager.discover()

            self.assertEqual(discovered, [])


class StreamPluginIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["APP_ENV"] = "development"
        cls.main = importlib.import_module("main")
        cls.main.app.config["TESTING"] = True
        cls.client = cls.main.app.test_client()

    def test_plugin_command_is_routed_by_manager(self):
        weather_payload = {
            "results": [{"name": "Seattle", "admin1": "Washington", "country": "United States", "latitude": 47.61, "longitude": -122.33}],
        }
        forecast_payload = {
            "current": {
                "temperature_2m": 14.2,
                "apparent_temperature": 13.5,
                "relative_humidity_2m": 76,
                "weather_code": 3,
                "wind_speed_10m": 11.4,
            },
            "current_units": {
                "temperature_2m": "C",
                "relative_humidity_2m": "%",
                "wind_speed_10m": "km/h",
            },
        }

        with mock.patch.object(
            self.main.PLUGIN_MANAGER.runtimes["weather"].instance,
            "_fetch_json",
            side_effect=[weather_payload, forecast_payload],
        ):
            response = self.client.post("/stream", json={"message": "/weather Seattle"})

        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("Seattle, Washington, United States: Overcast", body)

    def test_before_and_after_response_hooks_are_dispatched(self):
        with mock.patch.object(
            self.main,
            "_stream_chat_tokens",
            return_value=iter(["hello", " world"]),
        ):
            response = self.client.post("/stream", json={"message": "hello"})

        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn('"type": "done"', body)

        weather_runtime = self.main.PLUGIN_MANAGER.runtimes["weather"]
        self.assertIsNotNone(weather_runtime.instance.app_context)

    def test_plugin_manager_supports_reload(self):
        reloaded = self.main.PLUGIN_MANAGER.reload_plugin("weather")

        self.assertEqual(reloaded.manifest.plugin_api_version, PLUGIN_API_VERSION)
        self.assertEqual(self.main.PLUGIN_MANAGER.command_registry["/weather"], "weather")


class SshPluginTests(unittest.TestCase):
    def setUp(self):
        module = importlib.import_module("plugins.ssh.plugin")
        self.plugin = module.Plugin()
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.key_path = str(Path(self.tmpdir.name) / "ssh" / "id_ed25519")

        def fake_run(command, **kwargs):
            if command[0] == "ssh-keygen":
                private_key = Path(command[-1])
                private_key.parent.mkdir(parents=True, exist_ok=True)
                private_key.write_text("PRIVATE KEY", encoding="utf-8")
                Path(f"{private_key}.pub").write_text("PUBLIC KEY", encoding="utf-8")
                return mock.Mock(returncode=0, stdout="", stderr="")
            return mock.Mock(returncode=0, stdout="ok\n", stderr="")

        self.keygen_patcher = mock.patch("plugins.ssh.plugin.subprocess.run", side_effect=fake_run)
        self.mock_run = self.keygen_patcher.start()
        self.addCleanup(self.keygen_patcher.stop)

        self.plugin.on_load(
            {
                "config": {
                    "plugins": {
                        "ssh": {
                            "default_host": "holly-voice",
                            "connect_timeout_seconds": 3,
                            "command_timeout_seconds": 10,
                            "key_path": self.key_path,
                        }
                    }
                }
            }
        )

    def test_ssh_plugin_generates_keypair_on_load(self):
        self.assertTrue(Path(self.key_path).exists())
        self.assertTrue(Path(f"{self.key_path}.pub").exists())

    def test_ssh_plugin_runs_command_and_logs_it(self):
        completed = mock.Mock(returncode=0, stdout="ok\n", stderr="")
        with mock.patch("plugins.ssh.plugin.subprocess.run", return_value=completed) as run_mock:
            response = self.plugin.on_command("/ssh", ["hostname"], {"session_id": "s1", "username": "admin"})

        self.assertEqual(response["content"], "ok")
        run_mock.assert_called_once()
        called_command = run_mock.call_args.args[0]
        self.assertEqual(called_command[:3], ["ssh", "-i", self.key_path])
        self.assertIn("IdentitiesOnly=yes", called_command)
        self.assertEqual(called_command[-2:], ["holly@holly-voice", "hostname"])

    def test_ssh_plugin_tool_returns_structured_result(self):
        completed = mock.Mock(returncode=0, stdout="linux\n", stderr="")

        with mock.patch("plugins.ssh.plugin.subprocess.run", return_value=completed):
            result = self.plugin.call_tool(
                "ssh.run_command",
                {"host": "example-host", "command": "uname -s"},
                {"session_id": "s2"},
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["host"], "example-host")
        self.assertEqual(result["data"]["command"], "uname -s")
        called_command = self.plugin._normalize_host("example-host")
        self.assertEqual(called_command, "holly@example-host")

    def test_ssh_plugin_tool_rejects_placeholder_command_values(self):
        with self.assertRaisesRegex(ValueError, "actual remote command"):
            self.plugin.call_tool(
                "ssh.run_command",
                {"host": "holly-voice", "command": "ssh"},
                {"session_id": "s3"},
            )

        with self.assertRaisesRegex(ValueError, "actual remote command"):
            self.plugin.call_tool(
                "ssh.run_command",
                {"host": "holly-voice", "command": "ssh.run_command"},
                {"session_id": "s4"},
            )

    def test_ssh_plugin_tool_rejects_host_or_destination_as_command(self):
        with self.assertRaisesRegex(ValueError, "not just the host"):
            self.plugin.call_tool(
                "ssh.run_command",
                {"host": "holly-voice", "command": "holly-voice"},
                {"session_id": "s5"},
            )

        with self.assertRaisesRegex(ValueError, "not just the host"):
            self.plugin.call_tool(
                "ssh.run_command",
                {"host": "holly-voice", "command": "holly@holly-voice"},
                {"session_id": "s6"},
            )


if __name__ == "__main__":
    unittest.main()
