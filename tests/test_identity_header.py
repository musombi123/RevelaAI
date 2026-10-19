"""Identity hint consistency tests for the native FastAPI Smart Memory API."""
import time
import unittest
from unittest.mock import patch

import jwt
from fastapi.testclient import TestClient

from asgi import app
from fastapi_routes import auth


USER_ID = "507f1f77bcf86cd799439011"
OTHER_ID = "507f1f77bcf86cd799439099"
TEST_SECRET = "identity-header-test-secret"
client = TestClient(app)


class UserIdHeaderTests(unittest.TestCase):
    def setUp(self):
        self.jwt_patch = patch.object(auth, "JWT_SECRET", TEST_SECRET)
        self.jwt_patch.start()
        self.addCleanup(self.jwt_patch.stop)
        self.token = jwt.encode(
            {
                "sub": USER_ID,
                "user_id": USER_ID,
                "iat": int(time.time()),
                "exp": int(time.time()) + 300,
            },
            TEST_SECRET,
            algorithm="HS256",
        )

    def test_header_must_match_signed_token(self):
        response = client.post(
            "/api/memory/chat",
            headers={
                "Authorization": f"Bearer {self.token}",
                "userId": OTHER_ID,
            },
            json={"userMessage": "My farm grows maize"},
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "user_identity_mismatch")

    def test_body_cannot_conflict_with_valid_identity_header(self):
        response = client.post(
            "/api/memory/chat",
            headers={
                "Authorization": f"Bearer {self.token}",
                "userId": USER_ID,
            },
            json={"userId": OTHER_ID, "userMessage": "My farm grows maize"},
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "user_identity_mismatch")


if __name__ == "__main__":
    unittest.main()
