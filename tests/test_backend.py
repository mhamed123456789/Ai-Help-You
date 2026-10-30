import base64
from io import BytesIO
from datetime import datetime
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from fastapi.testclient import TestClient
from PIL import Image

from backend import MODEL_NAME, create_backend_app
from app_features import prepare_image_bytes
from credits import DailyCreditStore


class BackendEndpointTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.generate_content = Mock(return_value=SimpleNamespace(text="Hello from Gemini"))
        self.client_factory = Mock(
            return_value=SimpleNamespace(
                models=SimpleNamespace(generate_content=self.generate_content)
            )
        )
        self.credit_store = DailyCreditStore(
            f"{self.temporary.name}/credits.sqlite3",
            clock=lambda: datetime(2026, 10, 30, 12, 0).astimezone(),
        )
        app = create_backend_app(
            "test-session-token",
            client_factory=self.client_factory,
            api_key_provider=lambda: "test-key",
            credit_store=self.credit_store,
        )
        self.client = TestClient(app)
        self.headers = {"X-App-Token": "test-session-token"}

    def tearDown(self):
        self.temporary.cleanup()

    def test_health_requires_session_token_and_does_not_expose_api_key(self):
        unauthorized = self.client.get("/api/health")
        authorized = self.client.get("/api/health", headers=self.headers)

        self.assertEqual(unauthorized.status_code, 401)
        self.assertEqual(authorized.status_code, 200)
        self.assertEqual(
            authorized.json(),
            {
                "status": "ok",
                "model": MODEL_NAME,
                "gemini_configured": True,
            },
        )
        self.assertNotIn("test-key", authorized.text)

    def test_api_test_uses_expected_model_and_returns_response(self):
        response = self.client.post(
            "/api/gemini/test",
            headers=self.headers,
            json={"language": "English"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"model": MODEL_NAME, "reply": "Hello from Gemini"})
        self.generate_content.assert_called_once()
        self.assertEqual(self.generate_content.call_args.kwargs["model"], MODEL_NAME)

    def test_chat_passes_history_and_compressed_image_to_gemini(self):
        image_buffer = BytesIO()
        Image.new("RGB", (40, 30), "white").save(image_buffer, format="PNG")
        optimized_data, mime_type = prepare_image_bytes(
            "screen.png",
            image_buffer.getvalue(),
            "image/png",
        )
        image_data = base64.b64encode(optimized_data).decode("ascii")
        response = self.client.post(
            "/api/gemini/chat",
            headers=self.headers,
            json={
                "message": "What is in this screenshot?",
                "history": [
                    {"role": "user", "text": "Hi"},
                    {"role": "model", "text": "Hello"},
                ],
                "images": [
                    {
                        "name": "screen.png",
                        "mime_type": mime_type,
                        "data": image_data,
                    }
                ],
                "language": "English",
            },
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["reply"], "Hello from Gemini")
        contents = self.generate_content.call_args.kwargs["contents"]
        self.assertEqual([turn.role for turn in contents], ["user", "model", "user"])
        self.assertEqual(contents[0].parts[0].text, "Hi")
        self.assertEqual(contents[1].parts[0].text, "Hello")
        self.assertEqual(contents[2].parts[0].text, "What is in this screenshot?")
        self.assertEqual(contents[2].parts[1].inline_data.mime_type, "image/jpeg")

    def test_chat_rejects_malformed_image_payload(self):
        response = self.client.post(
            "/api/gemini/chat",
            headers=self.headers,
            json={
                "message": "Analyze this",
                "images": [
                    {
                        "name": "screen.png",
                        "mime_type": "image/png",
                        "data": "not-base64",
                    }
                ],
            },
        )

        self.assertEqual(response.status_code, 422)
        self.assertIn("valid base64", response.json()["detail"])
        self.generate_content.assert_not_called()

    def test_chat_charges_credits_and_exposes_remaining_balance(self):
        response = self.client.post(
            "/api/gemini/chat",
            headers=self.headers,
            json={"message": "Hi", "language": "English"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["credits_used"], 5)
        self.assertEqual(response.json()["credits"], 495)
        self.assertEqual(self.client.get("/api/credits", headers=self.headers).json()["credits"], 495)

    def test_exhausted_balance_locks_chat_without_requesting_gemini(self):
        for _ in range(25):
            self.client.app.state.credit_store.charge(20)
        self.generate_content.reset_mock()

        response = self.client.post(
            "/api/gemini/chat",
            headers=self.headers,
            json={"message": "Hi"},
        )

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json()["detail"]["credits"], 0)
        self.assertIn("00:00", response.json()["detail"]["message"])
        self.generate_content.assert_not_called()

    def test_partial_balance_rejects_expensive_message_but_does_not_lock_account(self):
        for _ in range(24):
            self.credit_store.charge(20)
        self.credit_store.charge(15)

        response = self.client.post(
            "/api/gemini/chat",
            headers=self.headers,
            json={"message": "x" * 1000},
        )

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json()["detail"]["credits"], 5)
        self.assertFalse(response.json()["detail"]["locked"])
        self.assertIn("Shorten it", response.json()["detail"]["message"])
        self.generate_content.assert_not_called()

    def test_gemini_failure_refunds_reserved_credits(self):
        self.generate_content.side_effect = RuntimeError("provider failed")

        response = self.client.post(
            "/api/gemini/chat",
            headers=self.headers,
            json={"message": "Hi"},
        )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(self.client.get("/api/credits", headers=self.headers).json()["credits"], 500)

    def test_missing_api_key_returns_clear_error(self):
        app = create_backend_app(
            "test-session-token",
            client_factory=self.client_factory,
            api_key_provider=lambda: None,
            credit_store=self.credit_store,
        )
        response = TestClient(app).post(
            "/api/gemini/test",
            headers=self.headers,
            json={"language": "English"},
        )

        self.assertEqual(response.status_code, 503)
        self.assertIn("GEMINI_API_KEY", response.json()["detail"])
        self.client_factory.assert_not_called()

    def test_gemini_authentication_errors_are_sanitized(self):
        error = RuntimeError("authentication failed with secret test-key")
        error.status_code = 403
        self.generate_content.side_effect = error

        response = self.client.post(
            "/api/gemini/test",
            headers=self.headers,
            json={"language": "English"},
        )

        self.assertEqual(response.status_code, 502)
        self.assertIn("rejected the API key", response.json()["detail"])
        self.assertNotIn("test-key", response.text)


if __name__ == "__main__":
    unittest.main()
