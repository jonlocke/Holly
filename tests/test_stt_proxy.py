import importlib
import io
import os
import unittest
from unittest import mock
from urllib import error as urllib_error


class _FakeHTTPResponse:
    def __init__(self, body=b"", status=200, content_type="application/json"):
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

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class SpeechToTextProxyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["APP_ENV"] = "development"
        module = importlib.import_module("main")
        module.app.config["TESTING"] = True
        cls.main = module
        cls.client = module.app.test_client()

    def test_speech_to_text_forwards_multipart_and_reads_json_text(self):
        seen = {}

        def fake_urlopen(req, timeout=0):
            seen["url"] = req.full_url
            seen["method"] = req.get_method()
            seen["headers"] = {k.lower(): v for k, v in req.header_items()}
            seen["body"] = req.data
            return _FakeHTTPResponse(body=b'{"text":"hello world"}', status=200, content_type="application/json")

        with (
            mock.patch.object(self.main, "WHISPER_CPP_STT_ENDPOINT", "http://stt.internal/inference"),
            mock.patch.object(self.main, "STT_UPSTREAM_FILE_FIELD", "file"),
            mock.patch.object(self.main.urllib_request, "urlopen", side_effect=fake_urlopen),
        ):
            response = self.client.post(
                "/speech-to-text",
                data={"audio": (io.BytesIO(b"fake-audio"), "speech.webm")},
                content_type="multipart/form-data",
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["text"], "hello world")
        self.assertEqual(seen["url"], "http://stt.internal/inference")
        self.assertEqual(seen["method"], "POST")
        self.assertIn("multipart/form-data", seen["headers"].get("content-type", ""))
        self.assertIn(b'name="file"; filename="speech.webm"', seen["body"])

    def test_speech_to_text_preserves_upstream_http_status(self):
        http_error = urllib_error.HTTPError(
            url="http://stt.internal/inference",
            code=400,
            msg="Bad Request",
            hdrs=None,
            fp=io.BytesIO(b'{"error":"unsupported format"}'),
        )

        with (
            mock.patch.object(self.main, "WHISPER_CPP_STT_ENDPOINT", "http://stt.internal/inference"),
            mock.patch.object(self.main.urllib_request, "urlopen", side_effect=http_error),
        ):
            response = self.client.post(
                "/speech-to-text",
                data={"audio": (io.BytesIO(b"fake-audio"), "speech.webm")},
                content_type="multipart/form-data",
            )

        self.assertEqual(response.status_code, 400)
        payload = response.get_json()
        self.assertEqual(payload["error"], "STT upstream HTTP 400")
        self.assertIn("unsupported format", payload["upstreamError"])


if __name__ == "__main__":
    unittest.main()
