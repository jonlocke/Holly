import importlib
import os
import unittest


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

        verify = self.client.post("/stream", json={"message": "/face-verify demo-token"})
        self.assertEqual(verify.status_code, 200)
        self.assertIn("Face verification successful", verify.get_data(as_text=True))

        status_after = self.client.post("/stream", json={"message": "/face-status"})
        self.assertEqual(status_after.status_code, 200)
        self.assertIn("Face verification active", status_after.get_data(as_text=True))

    def test_git_command_is_blocked_without_face_verification(self):
        response = self.client.post("/stream", json={"message": "/git https://github.com/octocat/Hello-World"})
        self.assertEqual(response.status_code, 403)
        self.assertIn("Step-up verification required", response.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
