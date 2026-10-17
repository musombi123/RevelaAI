import unittest
from unittest.mock import patch

from flask import Flask
from bson import ObjectId

from routes import memory_routes


USER_ID = "507f1f77bcf86cd799439011"


class FakeCursor:
    def __init__(self, documents):
        self.documents = documents

    def sort(self, *_args, **_kwargs):
        return self

    def limit(self, count):
        self.documents = self.documents[:count]
        return self

    def __iter__(self):
        return iter(self.documents)


class FakeCollection:
    def __init__(self, documents):
        self.documents = documents
        self.query = None

    def find(self, query, projection):
        self.query = (query, projection)
        return FakeCursor(self.documents)


class ConversationHistoryTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.register_blueprint(memory_routes.memory_bp, url_prefix="/api/memory")
        self.client = self.app.test_client()
        self.collection = FakeCollection([
            {
                "_id": ObjectId("507f1f77bcf86cd799439012"),
                "userId": ObjectId(USER_ID),
                "sessionId": "session-a",
                "hub": "mkulima",
                "messages": [
                    {"role": "user", "content": "My farm grows maize"},
                    {"role": "assistant", "content": "Let's review the crop stage"},
                ],
            }
        ])

    def test_owner_can_load_bounded_conversation_history(self):
        with patch.object(
            memory_routes, "_require_identity",
            return_value=(ObjectId(USER_ID), USER_ID, None),
        ), patch.object(memory_routes, "conversations", return_value=self.collection):
            response = self.client.get(f"/api/memory/conversations/{USER_ID}")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["userId"], USER_ID)
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["conversations"][0]["sessionId"], "session-a")
        self.assertEqual(len(payload["conversations"][0]["messages"]), 2)
        self.assertEqual(self.collection.query[0], {"userId": ObjectId(USER_ID)})

    def test_user_cannot_load_another_users_history(self):
        with patch.object(
            memory_routes, "_require_identity",
            return_value=(ObjectId(USER_ID), USER_ID, None),
        ):
            response = self.client.get("/api/memory/conversations/507f1f77bcf86cd799439099")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()["code"], "user_identity_mismatch")


if __name__ == "__main__":
    unittest.main()
