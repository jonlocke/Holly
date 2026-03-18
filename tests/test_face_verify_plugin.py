import importlib
import os
import tempfile
import unittest
from pathlib import Path

from plugin_system import PluginManager
from plugins.shared_assurance import build_assurance_payload, validate_assurance_payload


class AssuranceContractTests(unittest.TestCase):
    def test_valid_assurance_payload_passes(self):
        payload = build_assurance_payload(
            subject_id="user-1",
            session_id="session-1",
            factors_present=["face_verify"],
            factor_freshness={"face_verify": 123},
            face_score=0.99,
            liveness_status="pass",
            assurance_level="high",
            expires_at=999,
            issuer="face_verify",
            model_version="insightface-skeleton",
            reason_code="verified",
        )
        self.assertEqual(validate_assurance_payload(payload), (True, None))

    def test_missing_required_assurance_field_fails(self):
        payload = {"subject_id": "user-1"}
        valid, error = validate_assurance_payload(payload)
        self.assertFalse(valid)
        self.assertIn("Missing required assurance fields", error)

    def test_invalid_enum_value_fails(self):
        payload = build_assurance_payload(
            subject_id="user-1",
            session_id="session-1",
            factors_present=["face_verify"],
            factor_freshness={"face_verify": 123},
            face_score=0.99,
            liveness_status="maybe",
            assurance_level="high",
            expires_at=999,
            issuer="face_verify",
            model_version="insightface-skeleton",
            reason_code="verified",
        )
        valid, error = validate_assurance_payload(payload)
        self.assertFalse(valid)
        self.assertIn("Invalid liveness_status", error)


class FaceVerifyPluginIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["APP_ENV"] = "development"
        cls.main = importlib.import_module("main")
        cls.main.app.config["TESTING"] = True

    def setUp(self):
        self.client = self.main.app.test_client()

    def test_face_verify_commands_round_trip(self):
        enroll = self.client.post("/stream", json={"message": "/face-enroll demo-token"})
        self.assertEqual(enroll.status_code, 200)
        self.assertIn("Face token enrolled", enroll.get_data(as_text=True))

        status_before = self.client.post("/stream", json={"message": "/face-status"})
        self.assertEqual(status_before.status_code, 200)
        self.assertIn("not currently active", status_before.get_data(as_text=True))

        verify = self.client.post(
            "/stream",
            json={"message": "/face-verify demo-token --liveness=pass"},
        )
        self.assertEqual(verify.status_code, 200)
        self.assertIn("Face verification successful", verify.get_data(as_text=True))

        status_after = self.client.post("/stream", json={"message": "/face-status"})
        self.assertEqual(status_after.status_code, 200)
        self.assertIn("Face verification active", status_after.get_data(as_text=True))

    def test_git_command_is_blocked_without_face_verification(self):
        from unittest import mock

        with mock.patch.object(self.main, "GIT_ENDPOINT_TOKEN", "test-token"):
            response = self.client.post(
                "/stream",
                json={"message": "/git https://github.com/octocat/Hello-World"},
                headers={"X-Holly-Git-Token": "test-token"},
            )
        self.assertEqual(response.status_code, 403)
        self.assertIn("fresh face verification is required", response.get_data(as_text=True).lower())

    def test_face_verify_output_is_accepted_by_acl_rbac(self):
        self.client.post("/stream", json={"message": "/face-enroll demo-token"})
        self.client.post("/stream", json={"message": "/face-verify demo-token --liveness=pass"})
        runtime = self.main.PLUGIN_MANAGER.runtimes["face_verify"]
        with self.client.session_transaction() as session_state:
            session_id = session_state["session_id"]
        assurance = runtime.instance.build_assurance({"session_id": session_id})
        valid, error = validate_assurance_payload(assurance)
        self.assertTrue(valid, error)

    def test_missing_liveness_fails_verify(self):
        self.client.post("/stream", json={"message": "/face-enroll demo-token"})
        response = self.client.post("/stream", json={"message": "/face-verify demo-token"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("liveness was unavailable", response.get_data(as_text=True).lower())

    def test_invalid_provider_fails_safe(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = PluginManager(
                Path(__file__).resolve().parents[1] / "plugins",
                {
                    "config": {
                        "plugins": {
                            "face_verify": {
                                "store_path": str(Path(tmpdir) / "face_verify.json"),
                                "verify_ttl_seconds": 120,
                                "provider": "invalid-provider",
                                "sensitive_commands": ["/git"],
                            },
                            "acl_rbac": {
                                "policy_file_path": "policy-inline",
                                "default_role": "user",
                                "fail_closed": True,
                            },
                        }
                    },
                    "plugin_manager": None,
                },
                trusted_plugins={"face_verify"},
            )
            manifest = manager._load_manifest(Path(__file__).resolve().parents[1] / "plugins/face_verify/manifest.json")
            with self.assertRaises(ValueError):
                manager.load_plugin(Path(__file__).resolve().parents[1] / "plugins/face_verify", manifest=manifest)


if __name__ == "__main__":
    unittest.main()
