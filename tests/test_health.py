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


    def test_streamed_tts_prefers_paragraph_bullet_and_240ish_sentence_chunks(self):
        module = importlib.import_module("main")
        text = (
            "Short paragraph that should stay together.\n\n"
            "1. First numbered bullet sentence is substantial and should combine with the second sentence when still under the size target. "
            "Second sentence keeps it under the optimal boundary for one chunk.\n\n"
            "This final paragraph sentence is intentionally long enough that it needs to be split across multiple chunks because it keeps going "
            "with additional detail and still more detail so that the total character length exceeds the configured target size by a fair amount."
        )

        prepared = module._prepare_text_for_streamed_tts(text, max_chars=120)
        chunks = [chunk for chunk in prepared.split("\n\n") if chunk]

        self.assertGreaterEqual(len(chunks), 4)
        self.assertEqual(chunks[0], "Short paragraph that should stay together.")
        self.assertTrue(chunks[1].startswith("1. First numbered bullet"))
        self.assertLessEqual(len(chunks[1]), 120)
        self.assertTrue(all(len(chunk) <= 120 for chunk in chunks[1:]))

    def test_streamed_tts_combines_sentences_when_under_target(self):
        module = importlib.import_module("main")
        text = "Sentence one is short. Sentence two is short as well."

        prepared = module._prepare_text_for_streamed_tts(text, max_chars=240)

        self.assertEqual(prepared, text)

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
