import importlib
import io
import os
import unittest
from unittest import mock
from urllib import error as urllib_error
import socket


class _FakeHTTPResponse:
    def __init__(self, body=b"", status=200, content_type="application/octet-stream"):
        self._body = body
        self.status = status
        self.headers = {"Content-Type": content_type}

    def read(self, amt=-1):
        if amt is None or amt < 0:
            chunk = self._body
            self._body = b""
            return chunk
        chunk = self._body[:amt]
        self._body = self._body[amt:]
        return chunk

    def readline(self, limit=-1):
        if not self._body:
            return b""
        newline_index = self._body.find(b"\n")
        if newline_index == -1:
            return self.read(limit)
        end_index = newline_index + 1
        if limit is not None and limit >= 0:
            end_index = min(end_index, limit)
        line = self._body[:end_index]
        self._body = self._body[end_index:]
        return line

    def close(self):
        return None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


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
            mock.patch.object(self.main, "_resolve_qwen3_tts_speak_url", return_value=speak_url),
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
            mock.patch.object(self.main, "_resolve_qwen3_tts_speak_url", return_value=speak_url),
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

    def test_qwen3_timeout_from_upstream_forces_fallback(self):
        health_url = "http://tts.internal/health"
        speak_url = "http://tts.internal/speak"

        def fake_urlopen(req, timeout=0):
            if req.full_url == health_url and req.get_method() == "GET":
                return _FakeHTTPResponse(body=b'{"status":"ok"}', status=200, content_type="application/json")
            if req.full_url == speak_url and req.get_method() == "POST":
                raise socket.timeout("timed out")
            raise AssertionError(f"Unexpected upstream call to {req.full_url} ({req.get_method()})")

        with (
            mock.patch.object(self.main, "TTS_MODE", "qwen3"),
            mock.patch.object(self.main, "QWEN_TTS_HEALTH_URL", health_url),
            mock.patch.object(self.main, "_resolve_qwen3_tts_speak_url", return_value=speak_url),
            mock.patch.object(self.main.urllib_request, "urlopen", side_effect=fake_urlopen) as mocked_urlopen,
        ):
            response = self.client.post("/text-to-speech", json={"text": "Fallback on timeout"})

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["fallback"], "browser_speak")
        self.assertEqual(payload["text"], "Fallback on timeout")
        self.assertIn("Unable to reach TTS backend", payload["reason"])
        self.assertIn("timed out", payload["reason"])
        self.assertEqual(mocked_urlopen.call_count, 2)

    def test_qwen3_stream_mode_uses_stream_endpoint(self):
        health_url = "http://tts.internal/health"
        speak_url = "http://tts.internal/speak"
        stream_url = "http://tts.internal/speak?stream_audio_chunks=1&play=0&chunk=1&paragraph_chunking=1"

        def fake_urlopen(req, timeout=0):
            if req.full_url == health_url and req.get_method() == "GET":
                return _FakeHTTPResponse(body=b'{"status":"ok"}', status=200, content_type="application/json")
            if req.full_url == stream_url and req.get_method() == "POST":
                return _FakeHTTPResponse(
                    body=b'{"type":"audio_chunk","audio_b64_wav":"QQ=="}\n',
                    status=200,
                    content_type="application/x-ndjson",
                )
            raise AssertionError(f"Unexpected upstream call to {req.full_url} ({req.get_method()})")

        with (
            mock.patch.object(self.main, "TTS_MODE", "qwen3"),
            mock.patch.object(self.main, "QWEN_TTS_HEALTH_URL", health_url),
            mock.patch.object(self.main, "_resolve_qwen3_tts_speak_url", return_value=speak_url),
            mock.patch.object(self.main, "_resolve_qwen3_tts_stream_url", return_value=stream_url),
            mock.patch.object(self.main.urllib_request, "urlopen", side_effect=fake_urlopen) as mocked_urlopen,
        ):
            response = self.client.post("/text-to-speech?stream=1", json={"text": "Stream me"})

        self.assertEqual(response.status_code, 200)
        self.assertIn("application/x-ndjson", response.content_type)
        self.assertEqual(response.data, b'{"type":"audio_chunk","audio_b64_wav":"QQ=="}\n')
        self.assertEqual(mocked_urlopen.call_count, 2)
        called_urls = [call.args[0].full_url for call in mocked_urlopen.call_args_list]
        self.assertEqual(called_urls, [health_url, stream_url])


    def test_qwen3_retries_busy_tts_then_succeeds(self):
        health_url = "http://tts.internal/health"
        speak_url = "http://tts.internal/speak"
        busy_body = b'{"detail":"TTS synth is busy; retry shortly"}'
        side_effects = [
            _FakeHTTPResponse(body=b'{"status":"ok"}', status=200, content_type="application/json"),
            urllib_error.HTTPError(
                speak_url,
                429,
                "Too Many Requests",
                hdrs=None,
                fp=io.BytesIO(busy_body),
            ),
            urllib_error.HTTPError(
                speak_url,
                429,
                "Too Many Requests",
                hdrs=None,
                fp=io.BytesIO(busy_body),
            ),
            _FakeHTTPResponse(body=b"audio-bytes", status=200, content_type="audio/mpeg"),
        ]

        with (
            mock.patch.object(self.main, "TTS_MODE", "qwen3"),
            mock.patch.object(self.main, "QWEN_TTS_HEALTH_URL", health_url),
            mock.patch.object(self.main, "_resolve_qwen3_tts_speak_url", return_value=speak_url),
            mock.patch.object(self.main, "TTS_BUSY_RETRY_ATTEMPTS", 3),
            mock.patch.object(self.main, "TTS_BUSY_RETRY_DELAY_SECONDS", 0.0),
            mock.patch.object(self.main.time, "sleep") as mocked_sleep,
            mock.patch.object(self.main.urllib_request, "urlopen", side_effect=side_effects) as mocked_urlopen,
        ):
            response = self.client.post("/text-to-speech", json={"text": "retry me"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, b"audio-bytes")
        self.assertEqual(mocked_urlopen.call_count, 4)
        self.assertEqual(mocked_sleep.call_count, 2)

    def test_qwen3_returns_fallback_after_three_busy_retries(self):
        health_url = "http://tts.internal/health"
        speak_url = "http://tts.internal/speak"
        busy_body = b'{"detail":"TTS synth is busy; retry shortly"}'

        def fake_urlopen(req, timeout=0):
            if req.full_url == health_url and req.get_method() == "GET":
                return _FakeHTTPResponse(body=b'{"status":"ok"}', status=200, content_type="application/json")
            if req.full_url == speak_url and req.get_method() == "POST":
                raise urllib_error.HTTPError(
                    speak_url,
                    429,
                    "Too Many Requests",
                    hdrs=None,
                    fp=io.BytesIO(busy_body),
                )
            raise AssertionError(f"Unexpected upstream call to {req.full_url} ({req.get_method()})")

        with (
            mock.patch.object(self.main, "TTS_MODE", "qwen3"),
            mock.patch.object(self.main, "QWEN_TTS_HEALTH_URL", health_url),
            mock.patch.object(self.main, "_resolve_qwen3_tts_speak_url", return_value=speak_url),
            mock.patch.object(self.main, "TTS_BUSY_RETRY_ATTEMPTS", 3),
            mock.patch.object(self.main, "TTS_BUSY_RETRY_DELAY_SECONDS", 0.0),
            mock.patch.object(self.main.time, "sleep") as mocked_sleep,
            mock.patch.object(self.main.urllib_request, "urlopen", side_effect=fake_urlopen) as mocked_urlopen,
        ):
            response = self.client.post("/text-to-speech", json={"text": "fallback me"})

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["fallback"], "browser_speak")
        self.assertEqual(payload["text"], "fallback me")
        self.assertIn("busy", payload["reason"].lower())
        self.assertEqual(mocked_urlopen.call_count, 4)
        self.assertEqual(mocked_sleep.call_count, 2)



if __name__ == "__main__":
    unittest.main()
