from tests.elimu_test_support import complete_all_lessons, make_test_state


def test_certificate_is_cryptographically_signed_and_publicly_verifiable(monkeypatch):
    client, collections, private_key, claims, hub_id = make_test_state(monkeypatch)
    complete_all_lessons(client, hub_id)
    generated = client.post("/api/certificates/generate", json={"hub_id": hub_id})
    assert generated.status_code == 200, generated.text
    certificate_id = generated.json()["certificate_id"]

    key_response = client.get("/api/verify/certificate/public-key")
    assert key_response.status_code == 200
    assert key_response.json()["algorithm"] == "RS256"
    assert "BEGIN PUBLIC KEY" in key_response.json()["public_key_pem"]

    verified = client.get(f"/api/verify/certificate/{certificate_id}")
    assert verified.status_code == 200
    assert verified.json()["valid"] is True
    assert verified.json()["signature_fingerprint_sha256"]
    assert verified.json()["hub"]["progress_percent"] == 100

    # A record edited after issuance must no longer verify, even if the ID exists.
    collections["revela_certificates"].documents[0]["signed_token"] = "not-a-valid-signature"
    tampered = client.get(f"/api/verify/certificate/{certificate_id}")
    assert tampered.status_code == 200
    assert tampered.json()["valid"] is False


def test_certificate_public_metadata_must_match_signed_claims(monkeypatch):
    client, collections, _, _, hub_id = make_test_state(monkeypatch)
    complete_all_lessons(client, hub_id)
    generated = client.post("/api/certificates/generate", json={"hub_id": hub_id})
    assert generated.status_code == 200, generated.text
    certificate_id = generated.json()["certificate_id"]

    # The JWT still has a valid signature, but the public roles are changed in
    # storage. The verifier must compare displayed metadata with signed claims.
    collections["revela_certificates"].documents[0]["roles"] = ["Founder", "Forged Credential"]
    response = client.get(f"/api/verify/certificate/{certificate_id}")
    assert response.status_code == 200
    assert response.json()["valid"] is False
    assert response.json()["reason"] == "signature_invalid"
