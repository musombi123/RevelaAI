from tests.elimu_test_support import make_test_state


def test_profile_json_contains_account_and_hub_activity(monkeypatch):
    claims = {
        "sub": "64b0000000000000000000aa",
        "full_name": "Amina Learner",
        "contact": "amina@example.test",
        "role": "learner",
        "roles": ["learner", "builder"],
        "avatar_url": "https://assets.example.test/amina.png",
        "created_at": "2024-09-12T10:15:00+00:00",
    }
    progress = [{
        "user_id": claims["sub"],
        "hub_id": "64b000000000000000000001",
        "courses": [{"course_id": "course-foundations", "completed_lessons": ["lesson-01"], "status": "in_progress"}],
        "time_spent_seconds": 3660,
        "last_accessed": "2026-10-21T10:00:00+00:00",
    }]
    client, _, _, _, _ = make_test_state(monkeypatch, progress=progress, claims=claims)

    response = client.get("/api/accounts/profile/download?format=json")
    assert response.status_code == 200, response.text
    assert "application/json" in response.headers["content-type"]
    body = response.json()
    assert body["user"]["name"] == "Amina Learner"
    assert body["user"]["email"] == "amina@example.test"
    assert set(body["user"]["roles"]) >= {"learner", "builder"}
    assert len(body["hubs"]) == 1
    hub = body["hubs"][0]
    assert hub["name"] == "Data Literacy"
    assert hub["progress_percent"] == 50
    assert hub["completed_lessons"] == 1
    assert hub["time_spent_seconds"] == 3660
    assert hub["skills"]
    assert hub["instructors"] == ["Learning Team"]


def test_profile_pdf_download_has_pdf_content_disposition(monkeypatch):
    client, _, _, _, _ = make_test_state(monkeypatch)
    response = client.get("/api/accounts/profile/download?format=pdf")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("application/pdf")
    assert response.headers["content-disposition"].startswith("attachment;")
    assert "revelacode-profile-Test-Learner-" in response.headers["content-disposition"]
    assert response.content.startswith(b"%PDF-")
