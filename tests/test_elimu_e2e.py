from tests.elimu_test_support import complete_all_lessons, make_test_state


def test_elimu_hubs_course_progress_and_certificate_end_to_end(monkeypatch):
    client, collections, private_key, claims, hub_id = make_test_state(monkeypatch)

    listed = client.get("/api/elimu/hubs")
    assert listed.status_code == 200
    assert listed.headers["content-type"].startswith("application/json")
    assert listed.json()["count"] == 1
    assert listed.json()["hubs"][0]["name"] == "Data Literacy"

    details = client.get(f"/api/elimu/hubs/{hub_id}")
    assert details.status_code == 200
    assert len(details.json()["hub"]["courses"][0]["lessons"]) == 2

    course_id, result = complete_all_lessons(client, hub_id)
    assert result.json()["progress_percent"] == 100
    assert result.json()["hub_completed"] is True

    issued = client.post("/api/certificates/generate", json={"hub_id": hub_id})
    assert issued.status_code == 200, issued.text
    certificate_id = issued.json()["certificate_id"]
    assert certificate_id.startswith("RC-EL-")

    public = client.get(f"/api/verify/certificate/{certificate_id}")
    assert public.status_code == 200
    assert public.json()["valid"] is True
    assert public.json()["certified_by"] == "RevelaCode"
    assert "learner" in public.json()["roles"]
    assert "Elimu Learner" in public.json()["roles"]
    assert public.json()["signature_algorithm"] == "RS256"

    download = client.get(f"/api/certificates/{certificate_id}")
    assert download.status_code == 200
    assert download.headers["content-type"].startswith("application/pdf")
    assert download.content.startswith(b"%PDF-")

    # Completion is idempotent: repeated requests find the original issued record.
    issued_again = client.post("/api/certificates/generate", json={"hub_id": hub_id})
    assert issued_again.status_code == 200
    assert issued_again.json()["certificate_id"] == certificate_id
    assert issued_again.json()["already_issued"] is True


def test_hub_cannot_be_certified_before_all_lessons_are_complete(monkeypatch):
    client, _, _, _, hub_id = make_test_state(monkeypatch)
    response = client.post("/api/certificates/generate", json={"hub_id": hub_id})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "hub_not_complete"
