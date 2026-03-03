import importlib
import os
import time
import unittest
from unittest import mock
from urllib import error as urllib_error


class _FakeHTTPResponse:
    def __init__(self, body=b"", status=200, content_type="application/octet-stream"):
        self._body = body
        self.status = status
        self.headers = {"Content-Type": content_type}

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _SlowHTTPResponse(_FakeHTTPResponse):
    def __init__(self, delay_seconds, body=b"", status=200, content_type="application/octet-stream"):
        super().__init__(body=body, status=status, content_type=content_type)
        self.delay_seconds = delay_seconds

    def read(self):
        time.sleep(self.delay_seconds)
        return super().read()


class Qwen3TTSFallbackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["APP_ENV"] = "development"
        module = importlib.import_module("main")
        module.app.config["TESTING"] = True
        cls.main = module
        cls.client = module.app.test_client()

    def test_qwen3_healthy_probes_health_then_calls_speak(self):
        health_url = "http://tts.internal/health"
        speak_url = "http://tts.internal/speak"

        def fake_urlopen(req, timeout=0):
            if req.full_url == health_url and req.get_method() == "GET":
                return _FakeHTTPResponse(body=b'{"status":"ok"}', status=200, content_type="application/json")
            if req.full_url == speak_url and req.get_method() == "POST":
                return _FakeHTTPResponse(body=b"audio-bytes", status=200, content_type="audio/mpeg")
            raise AssertionError(f"Unexpected upstream call to {req.full_url} ({req.get_method()})")

        with (
            mock.patch.object(self.main, "TTS_MODE", "qwen3"),
            mock.patch.object(self.main, "QWEN_TTS_HEALTH_URL", health_url),
            mock.patch.object(self.main, "QWEN3_TTS_SPEAK_URL", speak_url),
            mock.patch.object(self.main.urllib_request, "urlopen", side_effect=fake_urlopen) as mocked_urlopen,
        ):
            response = self.client.post("/text-to-speech", json={"text": "Hello from test"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, b"audio-bytes")
        self.assertIn("audio/mpeg", response.content_type)
        self.assertEqual(mocked_urlopen.call_count, 2)
        called_urls = [call.args[0].full_url for call in mocked_urlopen.call_args_list]
        self.assertEqual(called_urls, [health_url, speak_url])

    def test_qwen3_unhealthy_health_check_forces_browser_fallback(self):
        health_url = "http://tts.internal/health"
        speak_url = "http://tts.internal/speak"

        with (
            mock.patch.object(self.main, "TTS_MODE", "qwen3"),
            mock.patch.object(self.main, "QWEN_TTS_HEALTH_URL", health_url),
            mock.patch.object(self.main, "QWEN3_TTS_SPEAK_URL", speak_url),
            mock.patch.object(
                self.main.urllib_request,
                "urlopen",
                side_effect=urllib_error.URLError("backend down"),
            ) as mocked_urlopen,
        ):
            response = self.client.post("/text-to-speech", json={"text": "Fallback text"})

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["fallback"], "browser_speak")
        self.assertEqual(payload["text"], "Fallback text")
        self.assertIn("health check failed", payload["reason"])
        self.assertEqual(mocked_urlopen.call_count, 1)
        self.assertEqual(mocked_urlopen.call_args[0][0].full_url, health_url)

    def test_qwen3_slow_speak_uses_timeout_fallback(self):
        health_url = "http://tts.internal/health"
        speak_url = "http://tts.internal/speak"

        def fake_urlopen(req, timeout=0):
            if req.full_url == health_url and req.get_method() == "GET":
                return _FakeHTTPResponse(body=b'{"status":"ok"}', status=200, content_type="application/json")
            if req.full_url == speak_url and req.get_method() == "POST":
                return _SlowHTTPResponse(delay_seconds=0.2, body=b"slow-audio", status=200, content_type="audio/mpeg")
            raise AssertionError(f"Unexpected upstream call to {req.full_url} ({req.get_method()})")

        with (
            mock.patch.object(self.main, "TTS_MODE", "qwen3"),
            mock.patch.object(self.main, "QWEN_TTS_HEALTH_URL", health_url),
            mock.patch.object(self.main, "QWEN3_TTS_SPEAK_URL", speak_url),
            mock.patch.object(self.main, "TTS_UPSTREAM_TOTAL_TIMEOUT_SECONDS", 0.05),
            mock.patch.object(self.main.urllib_request, "urlopen", side_effect=fake_urlopen) as mocked_urlopen,
        ):
            response = self.client.post("/text-to-speech", json={"text": "Fallback on timeout"})

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["fallback"], "browser_speak")
        self.assertEqual(payload["text"], "Fallback on timeout")
        self.assertIn("Unable to reach TTS backend", payload["reason"])
        self.assertIn("total timeout", payload["reason"])
        self.assertEqual(mocked_urlopen.call_count, 2)


if __name__ == "__main__":
    unittest.main()
