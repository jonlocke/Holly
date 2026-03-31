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


if __name__ == "__main__":
    unittest.main()
