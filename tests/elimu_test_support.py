"""Small in-memory fixtures for Elimu router tests; no external database is required."""
from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

from bson import ObjectId
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from fastapi.testclient import TestClient

import fastapi_routes.elimu as elimu_routes
from revela_platform.auth.auth_gate import enforce_auth


class FakeCursor(list):
    def sort(self, key, direction=1):
        super().sort(key=lambda row: row.get(key) or "", reverse=int(direction) < 0)
        return self


def matches(document, query):
    if not query:
        return True
    if "$or" in query:
        return any(matches(document, clause) for clause in query["$or"])
    for key, value in query.items():
        if document.get(key) != value:
            return False
    return True


class FakeCollection:
    def __init__(self, documents=None):
        self.documents = list(documents or [])

    def find_one(self, query=None):
        return next((row for row in self.documents if matches(row, query or {})), None)

    def find(self, query=None):
        return FakeCursor([row for row in self.documents if matches(row, query or {})])

    def replace_one(self, query, replacement, upsert=False):
        for index, row in enumerate(self.documents):
            if matches(row, query):
                value = dict(replacement)
                value.setdefault("_id", row.get("_id", ObjectId()))
                self.documents[index] = value
                return SimpleNamespace(matched_count=1, modified_count=1, upserted_id=None)
        if upsert:
            value = dict(replacement)
            value.setdefault("_id", ObjectId())
            self.documents.append(value)
            return SimpleNamespace(matched_count=0, modified_count=0, upserted_id=value["_id"])
        return SimpleNamespace(matched_count=0, modified_count=0, upserted_id=None)

    def insert_one(self, document):
        value = dict(document)
        value.setdefault("_id", ObjectId())
        self.documents.append(value)
        return SimpleNamespace(inserted_id=value["_id"])


def sample_hub():
    return {
        "_id": ObjectId("64b000000000000000000001"),
        "name": "Data Literacy",
        "description": "Introductory data analysis and evidence-based reasoning.",
        "skills": ["Data interpretation", "Critical thinking"],
        "instructors": [{"name": "Learning Team"}],
        "is_published": True,
        "courses": [
            {
                "id": "course-foundations",
                "title": "Foundations",
                "description": "Core data-literacy concepts.",
                "skills": ["Reading charts"],
                "lessons": [
                    {"id": "lesson-01", "title": "Understand a dataset", "description": "Identify fields and records."},
                    {"id": "lesson-02", "title": "Read a chart", "description": "Interpret a simple chart."},
                ],
            }
        ],
    }


def make_test_state(monkeypatch, *, progress=None, certificates=None, claims=None):
    hub = sample_hub()
    default_claims = {
        "sub": "64b0000000000000000000aa",
        "full_name": "Test Learner",
        "contact": "learner@example.test",
        "role": "learner",
        "roles": ["learner", "builder"],
        "verified": True,
    }
    identity = deepcopy(claims or default_claims)
    collections = {
        "elimu_hubs": FakeCollection([hub]),
        "elimu_progress": FakeCollection(progress or []),
        "revela_certificates": FakeCollection(certificates or []),
    }
    monkeypatch.setattr(elimu_routes, "collection", lambda name: collections[name])
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setattr(elimu_routes, "_get_private_key", lambda: private_key)
    monkeypatch.setattr(elimu_routes, "_get_public_key", lambda: private_key.public_key())

    app = FastAPI()
    app.include_router(elimu_routes.router)
    app.dependency_overrides[enforce_auth] = lambda: deepcopy(identity)
    return TestClient(app), collections, private_key, identity, str(hub["_id"])


def complete_all_lessons(client, hub_id):
    detail = client.get(f"/api/elimu/hubs/{hub_id}")
    assert detail.status_code == 200, detail.text
    course = detail.json()["hub"]["courses"][0]
    course_id = course["id"]
    start = client.post("/api/elimu/progress", json={"hub_id": hub_id, "course_id": course_id, "action": "start"})
    assert start.status_code == 200, start.text
    result = None
    for lesson in course["lessons"]:
        result = client.post(
            "/api/elimu/progress",
            json={
                "hub_id": hub_id,
                "course_id": course_id,
                "action": "complete_lesson",
                "lesson_id": lesson["id"],
            },
        )
        assert result.status_code == 200, result.text
    return course_id, result
