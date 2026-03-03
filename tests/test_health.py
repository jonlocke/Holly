import importlib
import os
import unittest


class HealthEndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["APP_ENV"] = "development"
        module = importlib.import_module("main")
        app = module.app
        app.config["TESTING"] = True
        cls.client = app.test_client()

    def test_health_returns_ok(self):
        response = self.client.get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"status": "ok"})

    def test_health_disallows_post(self):
        response = self.client.post("/health")

        self.assertEqual(response.status_code, 405)

    def test_health_sets_explicit_media_src_in_csp(self):
        response = self.client.get("/health")
        csp = response.headers.get("Content-Security-Policy", "")

        self.assertIn("default-src 'self'", csp)
        self.assertIn("media-src 'self' blob: data:", csp)

    def test_csp_media_source_normalizes_wrapped_quotes(self):
        module = importlib.import_module("main")

        self.assertEqual(
            module._csp_safe_media_source_from_url("'http://localhost:5500/speak?return_audio=true'"),
            "http://localhost:5500",
        )
        self.assertEqual(
            module._csp_safe_media_source_from_url('"https://example.com/path"'),
            "https://example.com",
        )

    def test_qwen_tts_resolver_strips_wrapping_quotes(self):
        module = importlib.import_module("main")
        with unittest.mock.patch.dict(
            os.environ,
            {
                "QWEN_TTS_API_BASE": '"http://localhost:5500"',
                "QWEN_TTS_ENDPOINT": "'/speak?return_audio=true&play=false'",
            },
            clear=False,
        ):
            self.assertEqual(
                module._resolve_qwen_tts_url(),
                "http://localhost:5500/speak?return_audio=true&play=false",
            )
