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
