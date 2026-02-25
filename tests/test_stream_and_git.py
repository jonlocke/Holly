import importlib
import ipaddress
import os
import unittest
from unittest import mock


class StreamAndGitEndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["APP_ENV"] = "development"
        module = importlib.import_module("main")
        module.app.config["TESTING"] = True
        cls.main = module
        cls.client = module.app.test_client()

    def test_stream_rejects_missing_message(self):
        response = self.client.post("/stream", json={})

        self.assertEqual(response.status_code, 400)
        body = response.get_data(as_text=True)
        self.assertIn("Invalid message", body)

    def test_stream_rejects_large_request_body(self):
        with mock.patch.object(self.main, "MAX_STREAM_BODY_BYTES", 10):
            response = self.client.post(
                "/stream",
                data='{"message":"this is too large"}',
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 413)
        self.assertIn("Request body is too large", response.get_data(as_text=True))

    def test_stream_sanitizes_backend_errors(self):
        with mock.patch.object(
            self.main,
            "_stream_chat_tokens",
            side_effect=RuntimeError("secret upstream details"),
        ):
            response = self.client.post("/stream", json={"message": "hello"})

        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("Unable to process request right now.", body)
        self.assertNotIn("secret upstream details", body)

    def test_git_requires_configured_server_token(self):
        with mock.patch.object(self.main, "GIT_ENDPOINT_TOKEN", ""):
            response = self.client.post("/stream", json={"message": "/git https://example.com/repo.git"})

        self.assertEqual(response.status_code, 503)
        self.assertIn("disabled by server configuration", response.get_data(as_text=True))

    def test_git_requires_authentication(self):
        with mock.patch.object(self.main, "GIT_ENDPOINT_TOKEN", "test-token"):
            response = self.client.post("/stream", json={"message": "/git https://example.com/repo.git"})

        self.assertEqual(response.status_code, 401)
        self.assertIn("Unauthorized", response.get_data(as_text=True))

    def test_git_rejects_urls_with_credentials(self):
        with mock.patch.object(self.main, "GIT_ENDPOINT_TOKEN", "test-token"):
            response = self.client.post(
                "/stream",
                json={"message": "/git https://user:pass@example.com/repo.git"},
                headers={"X-Holly-Git-Token": "test-token"},
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("must not include embedded credentials", response.get_data(as_text=True))

    def test_git_rejects_private_resolved_address(self):
        with (
            mock.patch.object(self.main, "GIT_ENDPOINT_TOKEN", "test-token"),
            mock.patch.object(
                self.main,
                "_resolve_hostname_ips",
                return_value=[ipaddress.ip_address("127.0.0.1")],
            ),
        ):
            response = self.client.post(
                "/stream",
                json={"message": "/git https://example.com/repo.git"},
                headers={"Authorization": "Bearer test-token"},
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("blocked network address", response.get_data(as_text=True))

    def test_git_accepts_safe_url_with_auth(self):
        with (
            mock.patch.object(self.main, "GIT_ENDPOINT_TOKEN", "test-token"),
            mock.patch.object(
                self.main,
                "_resolve_hostname_ips",
                return_value=[ipaddress.ip_address("93.184.216.34")],
            ),
            mock.patch.object(self.main, "_index_git_repository", return_value=(3, 8)) as index_repo,
        ):
            response = self.client.post(
                "/stream",
                json={"message": "/git https://example.com/repo.git"},
                headers={"X-Holly-Git-Token": "test-token"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn("Indexed repository", response.get_data(as_text=True))
        index_repo.assert_called_once()


if __name__ == "__main__":
    unittest.main()
