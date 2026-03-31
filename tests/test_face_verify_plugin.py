import importlib
import os
import tempfile
import unittest
import uuid
from pathlib import Path

from plugin_system import PluginManager
from plugins.acl_rbac.plugin import Plugin as AclRbacPlugin
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


class AclRbacPolicyTests(unittest.TestCase):
    def setUp(self):
        self.plugin = AclRbacPlugin()

    def test_known_high_and_critical_commands_are_explicitly_mapped(self):
        self.assertEqual(self.plugin.command_risk("/git"), "high")
        self.assertEqual(self.plugin.command_risk("/reboot"), "critical")
        self.assertEqual(self.plugin.command_risk("/shutdown"), "critical")

    def test_unknown_command_uses_deterministic_default_risk(self):
        self.assertEqual(self.plugin.command_risk("/unknown-command"), self.plugin.DEFAULT_RISK_LEVEL)

    def test_medium_risk_command_does_not_require_face_assurance(self):
        result = self.plugin.on_before_response({"message": "/face-clear", "session_id": "session-1"})
        self.assertIsNone(result)

    def test_high_risk_command_denies_when_assurance_missing(self):
        result = self.plugin.on_before_response({"message": "/git https://example.com/repo.git", "session_id": "session-1"})
        self.assertTrue(result["deny"])
        self.assertEqual(result["risk_level"], "high")
        self.assertEqual(result["reason_code"], "invalid_assurance")

    def test_high_risk_command_allows_valid_fresh_assurance(self):
        future_expiry = 2_000_000_000
        assurance = build_assurance_payload(
            subject_id="user-1",
            session_id="session-1",
            factors_present=["face_verify"],
            factor_freshness={"face_verify": future_expiry},
            face_score=0.99,
            liveness_status="pass",
            assurance_level="high",
            expires_at=future_expiry,
            issuer="face_verify",
            model_version="insightface-skeleton",
            reason_code="verified",
        )
        result = self.plugin.on_before_response(
            {
                "message": "/git https://example.com/repo.git",
                "session_id": "session-1",
                "face_assurance": assurance,
            }
        )
        self.assertIsNone(result)


class FaceVerifyPluginIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["APP_ENV"] = "development"
        cls.main = importlib.import_module("main")
        cls.main.app.config["TESTING"] = True

    def setUp(self):
        self.client = self.main.app.test_client()

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
        username, signature = self._create_user_with_enrolled_face("git-blocked")
        login = self._login_user_with_face(username, signature)
        self.assertEqual(login.status_code, 200)

        response = self.client.post(
            "/stream",
            json={"message": "/git https://github.com/octocat/Hello-World"},
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

    def test_face_capture_enroll_and_verify_round_trip(self):
        signature = [120] * 256

        enroll = self.client.post("/face-capture", json={"action": "enroll", "signature": signature})
        self.assertEqual(enroll.status_code, 400)

        gradient_signature = [index % 256 for index in range(256)]
        enroll = self.client.post("/face-capture", json={"action": "enroll", "signature": gradient_signature})
        self.assertEqual(enroll.status_code, 200)
        self.assertIn("Camera enrollment complete", enroll.get_json()["content"])

        verify = self.client.post(
            "/face-capture",
            json={"action": "verify", "signature": gradient_signature, "liveness": "pass"},
        )
        self.assertEqual(verify.status_code, 200)
        payload = verify.get_json()
        self.assertTrue(payload["ok"])
        self.assertIn("Face verification successful", payload["content"])

    def test_admin_can_create_user_enroll_face_and_sign_in(self):
        username, signature = self._create_user_with_enrolled_face("login")
        login = self._login_user_with_face(username, signature)
        self.assertEqual(login.status_code, 200)
        payload = login.get_json()
        self.assertTrue(payload["auth"]["authenticated"])
        self.assertEqual(payload["auth"]["user"]["username"], username)
        self.assertIn("face match confidence", payload["content"].lower())

    def test_signed_in_user_can_request_step_up_with_face(self):
        username, signature = self._create_user_with_enrolled_face("step-up")
        login = self._login_user_with_face(username, signature)
        self.assertEqual(login.status_code, 200)

        step_up = self.client.post(
            "/face-capture",
            json={"action": "verify", "mode": "step_up", "username": username, "signature": signature, "liveness": "pass"},
        )
        self.assertEqual(step_up.status_code, 200)
        payload = step_up.get_json()
        self.assertTrue(payload["auth"]["stepUpActive"])
        self.assertIn("Step-up verification active", payload["content"])
        self.assertIn("face match confidence", payload["content"].lower())

    def test_user_can_sign_in_with_password_after_admin_sets_one(self):
        username, _ = self._create_user_with_enrolled_face("password-login")
        reset = self.client.post(
            f"/admin/users/{username}/password",
            json={"new_password": "userpass123"},
        )
        self.assertEqual(reset.status_code, 200)

        response = self.client.post(
            "/auth/login",
            json={"username": username, "password": "userpass123"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["auth"]["authenticated"])
        self.assertEqual(payload["auth"]["user"]["username"], username)

    def test_signed_in_user_can_change_their_own_password(self):
        username, _ = self._create_user_with_enrolled_face("password-change")
        reset = self.client.post(
            f"/admin/users/{username}/password",
            json={"new_password": "firstpass123"},
        )
        self.assertEqual(reset.status_code, 200)

        login = self.client.post(
            "/auth/login",
            json={"username": username, "password": "firstpass123"},
        )
        self.assertEqual(login.status_code, 200)

        change = self.client.post(
            "/auth/password",
            json={"current_password": "firstpass123", "new_password": "secondpass123"},
        )
        self.assertEqual(change.status_code, 200)
        self.assertTrue(change.get_json()["auth"]["user"]["has_password"])

        self.client.post("/auth/logout")
        relogin = self.client.post(
            "/auth/login",
            json={"username": username, "password": "secondpass123"},
        )
        self.assertEqual(relogin.status_code, 200)

    def test_signed_in_user_can_reenroll_their_own_face(self):
        username, signature = self._create_user_with_enrolled_face("self-reenroll")
        login = self._login_user_with_face(username, signature)
        self.assertEqual(login.status_code, 200)

        updated_signature = [255 - (index % 256) for index in range(256)]
        reenroll = self.client.post(
            "/face-capture",
            json={"action": "enroll", "mode": "self-enroll", "signature": updated_signature},
        )
        self.assertEqual(reenroll.status_code, 200)
        self.assertIn("Face enrollment updated", reenroll.get_json()["content"])

        self.client.post("/auth/logout")
        old_login = self._login_user_with_face(username, signature)
        self.assertEqual(old_login.status_code, 403)
        new_login = self._login_user_with_face(username, updated_signature)
        self.assertEqual(new_login.status_code, 200)

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
