import os
import time
import unittest

import jwt
from flask import Flask
from bson import ObjectId

from routes import memory_routes


USER_ID = "507f1f77bcf86cd799439011"
OTHER_ID = "507f1f77bcf86cd799439099"


class UserIdHeaderTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.register_blueprint(memory_routes.memory_bp, url_prefix="/api/memory")
        self.client = self.app.test_client()
        self.token = jwt.encode(
            {
                "sub": USER_ID,
                "user_id": USER_ID,
                "iat": int(time.time()),
                "exp": int(time.time()) + 300,
            },
            os.environ["JWT_SECRET"],
            algorithm="HS256",
        )

    def test_header_must_match_signed_token(self):
        response = self.client.post(
            "/api/memory/chat",
            headers={
                "Authorization": f"Bearer {self.token}",
                "userId": OTHER_ID,
            },
            json={"userMessage": "My farm grows maize"},
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()["code"], "user_identity_mismatch")

    def test_body_cannot_conflict_with_valid_identity_header(self):
        response = self.client.post(
            "/api/memory/chat",
            headers={
                "Authorization": f"Bearer {self.token}",
                "userId": USER_ID,
            },
            json={"userId": OTHER_ID, "userMessage": "My farm grows maize"},
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()["code"], "user_identity_mismatch")


if __name__ == "__main__":
    unittest.main()
