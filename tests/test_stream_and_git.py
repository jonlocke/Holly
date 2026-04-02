import importlib
import ipaddress
import json
import os
import unittest
import uuid
from unittest import mock


class _FakeUrlopenResponse:
    def __init__(self, body: bytes = b"", headers: dict | None = None, status: int = 200):
        self._body = body
        self.headers = headers or {}
        self.status = status

    def read(self) -> bytes:
        return self._body

    def close(self):
        return None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class StreamAndGitEndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["APP_ENV"] = "development"
        module = importlib.import_module("main")
        module.app.config["TESTING"] = True
        cls.main = module

    def setUp(self):
        self.client = self.main.app.test_client()
        self.main._rate_limit_events["git"].clear()

    def _create_user_with_enrolled_face(self, username_prefix: str = "user") -> tuple[str, list[int]]:
        username = f"{username_prefix}-{uuid.uuid4().hex[:8]}"
        signature = [index % 256 for index in range(256)]
        admin_login = self.client.post(
            "/admin/login",
            json={"username": "admin", "password": "adminpass123"},
        )
        self.assertEqual(admin_login.status_code, 200)
        create_user = self.client.post(
            "/admin/users",
            json={"username": username, "display_name": username},
        )
        self.assertEqual(create_user.status_code, 201)
        enroll = self.client.post(
            "/face-capture",
            json={"action": "enroll", "username": username, "signature": signature},
        )
        self.assertEqual(enroll.status_code, 200)
        return username, signature

    def _login_user_with_face(self, username: str, signature: list[int]):
        return self.client.post(
            "/face-capture",
            json={"action": "verify", "mode": "login", "username": username, "signature": signature, "liveness": "pass"},
        )

    def _step_up_user_with_face(self, username: str, signature: list[int]):
        return self.client.post(
            "/face-capture",
            json={"action": "verify", "mode": "step_up", "username": username, "signature": signature, "liveness": "pass"},
        )

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


    def test_stream_returns_timeout_specific_message(self):
        with mock.patch.object(
            self.main,
            "_stream_chat_tokens",
            side_effect=RuntimeError("Gateway chat request timed out."),
        ):
            response = self.client.post("/stream", json={"message": "hello"})

        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("The model request timed out; please try again.", body)

    def test_session_info_marks_new_session_once(self):
        first_response = self.client.get("/session-info")
        self.assertEqual(first_response.status_code, 200)
        first_payload = first_response.get_json()
        self.assertTrue(first_payload["newSession"])
        self.assertIn("model", first_payload)

        second_response = self.client.get("/session-info")
        self.assertEqual(second_response.status_code, 200)
        second_payload = second_response.get_json()
        self.assertFalse(second_payload["newSession"])

    def test_chat_timeout_has_minimum_of_two_minutes(self):
        with mock.patch.dict(os.environ, {"CHAT_REQUEST_TIMEOUT_SECONDS": "30"}, clear=False):
            timeout = self.main._load_chat_request_timeout_seconds()

        self.assertEqual(timeout, 120.0)

    def test_voice_lists_remote_tts_voices(self):
        with (
            mock.patch.dict(os.environ, {"QWEN_TTS_VOICE": "ryan"}, clear=False),
            mock.patch.object(
                self.main,
                "_list_available_tts_voices",
                return_value=("ryan", ["alloy", "ryan", "sarah"]),
            ),
        ):
            response = self.client.post("/stream", json={"message": "/voice"})

        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("Configured voice: ryan", body)
        self.assertIn("Available remote TTS voices:", body)
        self.assertIn("- alloy", body)
        self.assertIn("- sarah", body)

    def test_voice_sets_session_tts_voice(self):
        with mock.patch.object(
            self.main,
            "_list_available_tts_voices",
            return_value=("ryan", ["alloy", "liz", "ryan"]),
        ):
            response = self.client.post("/stream", json={"message": "/voice liz"})

        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("Session TTS voice set to 'liz'.", body)

        with self.client.session_transaction() as session_state:
            self.assertEqual(session_state.get("tts_voice"), "liz")

    def test_voice_rejects_unknown_voice_name(self):
        with mock.patch.object(
            self.main,
            "_list_available_tts_voices",
            return_value=("ryan", ["alloy", "liz", "ryan"]),
        ):
            response = self.client.post("/stream", json={"message": "/voice unknown"})

        self.assertEqual(response.status_code, 400)
        body = response.get_data(as_text=True)
        self.assertIn("Unknown TTS voice 'unknown'.", body)
        self.assertIn("Available voices:", body)

    def test_voice_returns_fallback_message_when_remote_lookup_fails(self):
        with (
            mock.patch.dict(os.environ, {"QWEN_TTS_VOICE": "ryan"}, clear=False),
            mock.patch.object(
                self.main,
                "_list_available_tts_voices",
                side_effect=RuntimeError("TTS voices endpoint returned HTTP 404"),
            ),
        ):
            response = self.client.post("/stream", json={"message": "/voice"})

        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("Configured voice: ryan", body)
        self.assertIn("Unable to fetch available remote TTS voices.", body)
        self.assertIn("HTTP 404", body)

    def test_text_to_speech_proxy_injects_selected_session_voice(self):
        captured_payloads: list[dict] = []

        def fake_urlopen(req, timeout=0):
            if req.full_url == "http://tts.example/health":
                return _FakeUrlopenResponse(b"{}")

            captured_payloads.append(json.loads(req.data.decode("utf-8")))
            return _FakeUrlopenResponse(b"RIFFdemo", headers={"Content-Type": "audio/wav"})

        with (
            self.client.session_transaction() as session_state,
        ):
            session_state["tts_voice"] = "liz"

        with (
            mock.patch.object(self.main, "TTS_MODE", "qwen3"),
            mock.patch.object(self.main, "QWEN_TTS_HEALTH_URL", "http://tts.example/health"),
            mock.patch.object(self.main, "_resolve_qwen3_tts_speak_url", return_value="http://tts.example/speak"),
            mock.patch.object(self.main, "_resolve_qwen3_tts_stream_url", return_value="http://tts.example/speak-stream"),
            mock.patch.object(self.main.urllib_request, "urlopen", side_effect=fake_urlopen),
        ):
            response = self.client.post("/text-to-speech", json={"text": "Hello world"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(captured_payloads[0]["voice"], "liz")
        self.assertEqual(captured_payloads[0]["text"], "Hello world")

    def test_text_to_speech_proxy_preserves_explicit_voice(self):
        captured_payloads: list[dict] = []

        def fake_urlopen(req, timeout=0):
            if req.full_url == "http://tts.example/health":
                return _FakeUrlopenResponse(b"{}")

            captured_payloads.append(json.loads(req.data.decode("utf-8")))
            return _FakeUrlopenResponse(b"RIFFdemo", headers={"Content-Type": "audio/wav"})

        with (
            self.client.session_transaction() as session_state,
        ):
            session_state["tts_voice"] = "liz"

        with (
            mock.patch.object(self.main, "TTS_MODE", "qwen3"),
            mock.patch.object(self.main, "QWEN_TTS_HEALTH_URL", "http://tts.example/health"),
            mock.patch.object(self.main, "_resolve_qwen3_tts_speak_url", return_value="http://tts.example/speak"),
            mock.patch.object(self.main, "_resolve_qwen3_tts_stream_url", return_value="http://tts.example/speak-stream"),
            mock.patch.object(self.main.urllib_request, "urlopen", side_effect=fake_urlopen),
        ):
            response = self.client.post("/text-to-speech", json={"text": "Hello world", "voice": "alloy"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(captured_payloads[0]["voice"], "alloy")

    def test_stream_can_execute_plugin_tool_for_weather(self):
        tool_request = '{"tool":"weather.get_current_weather","arguments":{"location":"London"}}'
        final_answer = "It is currently overcast in London."

        with mock.patch.object(
            self.main,
            "_stream_chat_tokens",
            side_effect=[iter([tool_request])],
        ), mock.patch.object(
            self.main,
            "_stream_chat_events",
            return_value=iter([{"type": "token", "content": final_answer}]),
        ), mock.patch.object(
            self.main.PLUGIN_MANAGER,
            "dispatch_tool",
            return_value={
                "ok": True,
                "tool_name": "weather.get_current_weather",
                "content": "London: Overcast, 12C.",
                "data": {"location": "London", "weather_summary": "Overcast"},
            },
        ) as dispatch_tool:
            response = self.client.post("/stream", json={"message": "What's the weather in London?"})

        self.assertEqual(response.status_code, 200)
        self.assertIn(final_answer, response.get_data(as_text=True))
        dispatch_tool.assert_called_once_with(
            "weather.get_current_weather",
            {"location": "London"},
            mock.ANY,
        )

    def test_stream_uses_second_pass_when_selector_returns_no_tool_json(self):
        selector_response = '{"tool":null,"arguments":{}}'
        final_answer = "Hello there."

        with mock.patch.object(
            self.main,
            "_stream_chat_tokens",
            side_effect=[iter([selector_response])],
        ) as stream_mock, mock.patch.object(
            self.main,
            "_stream_chat_events",
            return_value=iter([{"type": "token", "content": final_answer}]),
        ) as event_mock, mock.patch.object(
            self.main.PLUGIN_MANAGER,
            "dispatch_tool",
        ) as dispatch_tool:
            response = self.client.post("/stream", json={"message": "Hello there."})

        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn(final_answer, body)
        dispatch_tool.assert_not_called()
        self.assertEqual(stream_mock.call_count, 1)
        self.assertEqual(event_mock.call_count, 1)

    def test_coerce_stream_text_accepts_reasoning_lists(self):
        value = [
            {"type": "reasoning", "text": "step one"},
            {"type": "reasoning", "content": " and step two"},
        ]

        self.assertEqual(self.main._coerce_stream_text(value), "step one and step two")

    def test_stream_chat_tokens_ignores_thinking_events(self):
        with mock.patch.object(
            self.main,
            "_stream_chat_events",
            return_value=iter(
                [
                    {"type": "thinking", "content": "internal"},
                    {"type": "token", "content": "visible"},
                ]
            ),
        ):
            chunks = list(self.main._stream_chat_tokens("hello"))

        self.assertEqual(chunks, ["visible"])

    def test_tool_request_parser_accepts_fenced_json_with_alias_tool_name(self):
        payload = self.main._parse_llm_tool_request(
            """
            To get the weather, use this:

            ```json
            {"tool":"Weather","arguments":{"location":"London"}}
            ```
            """
        )

        self.assertEqual(
            payload,
            {
                "tool": "weather.get_current_weather",
                "arguments": {"location": "London"},
            },
        )

    def test_tool_request_parser_accepts_embedded_json_object(self):
        payload = self.main._parse_llm_tool_request(
            'I should call {"tool":"get_current_weather","arguments":{"location":"Seattle"}} before answering.'
        )

        self.assertEqual(
            payload,
            {
                "tool": "weather.get_current_weather",
                "arguments": {"location": "Seattle"},
            },
        )

    def test_tool_request_parser_accepts_explicit_no_tool_json(self):
        payload = self.main._parse_llm_tool_request(
            '{"tool":null,"arguments":{}}'
        )

        self.assertEqual(
            payload,
            {
                "tool": None,
                "arguments": {},
            },
        )

    def test_tool_selection_prompt_requires_verbatim_command_arguments(self):
        prompt = self.main._tool_selection_prompt(
            [
                {
                    "name": "weather.get_current_weather",
                    "description": "Get the current weather for a location.",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "location": {"type": "string"},
                        },
                        "required": ["location"],
                    },
                }
            ],
            "What is the weather in London?",
        )

        self.assertIn("copy that value verbatim from the user request", prompt)
        self.assertIn("Do not rewrite, expand, explain, or invent arguments.", prompt)
        self.assertIn('{"tool":null,"arguments":{}}', prompt)
        self.assertIn("Do not answer the user directly in this step.", prompt)
    def test_tool_result_prompt_requires_single_clarification_question_for_errors(self):
        prompt = self.main._build_tool_result_prompt(
            "What is the weather in London?",
            "weather.get_current_weather",
            {"location": "London"},
            {
                "ok": False,
                "tool_name": "weather.get_current_weather",
                "error": "Location lookup failed.",
                "error_type": "ValueError",
            },
        )

        self.assertIn("respond with exactly two sentences", prompt)
        self.assertIn("ask one short clarification question", prompt)
        self.assertIn("Do not answer your own question.", prompt)
        self.assertIn("Do not include markdown, bullets, labels, examples, code fences, or multiple questions.", prompt)

    def test_tool_prompts_are_loaded_from_prompt_files(self):
        self.assertTrue(self.main.TOOL_SELECTION_PROMPT_PATH.exists())
        self.assertTrue(self.main.TOOL_RESULT_PROMPT_PATH.exists())
        self.assertIn(
            "copy that value verbatim from the user request",
            self.main.TOOL_SELECTION_PROMPT_PATH.read_text(encoding="utf-8"),
        )
        self.assertIn(
            "respond with exactly two sentences",
            self.main.TOOL_RESULT_PROMPT_PATH.read_text(encoding="utf-8"),
        )

    def test_git_api_requires_configured_server_token(self):
        api_client = self.main.app.test_client(use_cookies=False)
        with mock.patch.object(self.main, "GIT_ENDPOINT_TOKEN", ""):
            response = api_client.post("/stream", json={"message": "/git https://example.com/repo.git"})

        self.assertEqual(response.status_code, 503)
        self.assertIn("git api is disabled", response.get_data(as_text=True).lower())

    def test_git_api_requires_authentication(self):
        api_client = self.main.app.test_client(use_cookies=False)
        with mock.patch.object(self.main, "GIT_ENDPOINT_TOKEN", "test-token"):
            response = api_client.post("/stream", json={"message": "/git https://example.com/repo.git"})

        self.assertEqual(response.status_code, 401)
        self.assertIn("Unauthorized", response.get_data(as_text=True))

    def test_git_browser_session_relies_on_policy_not_token(self):
        with (
            mock.patch.object(self.main, "GIT_ENDPOINT_TOKEN", ""),
            mock.patch.object(
                self.main,
                "_resolve_hostname_ips",
                return_value=[ipaddress.ip_address("93.184.216.34")],
            ),
            mock.patch.object(self.main, "_index_git_repository", return_value=(3, 8)) as index_repo,
        ):
            username, signature = self._create_user_with_enrolled_face("browser-git")
            self._login_user_with_face(username, signature)
            self._step_up_user_with_face(username, signature)
            response = self.client.post(
                "/stream",
                json={"message": "/git https://example.com/repo.git"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn("Indexed repository", response.get_data(as_text=True))
        index_repo.assert_called_once()

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
            username, signature = self._create_user_with_enrolled_face("private-address")
            self._login_user_with_face(username, signature)
            self._step_up_user_with_face(username, signature)
            response = self.client.post(
                "/stream",
                json={"message": "/git https://example.com/repo.git"},
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
            username, signature = self._create_user_with_enrolled_face("safe-git")
            self._login_user_with_face(username, signature)
            self._step_up_user_with_face(username, signature)
            response = self.client.post(
                "/stream",
                json={"message": "/git https://example.com/repo.git"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn("Indexed repository", response.get_data(as_text=True))
        index_repo.assert_called_once()


if __name__ == "__main__":
    unittest.main()
