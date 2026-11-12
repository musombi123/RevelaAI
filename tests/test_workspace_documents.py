import json

import pytest

from fastapi_routes import workspace


def test_official_document_detection_recognizes_official_documents_and_institutional_proposals():
    body = workspace.WorkspaceExecuteInput(
        prompt="Make these official documents for an institutional introduction and collaboration proposal.",
        task="document",
    )
    assert workspace._is_official_document(body) is True


def test_multiple_document_payload_requires_exact_requested_count(monkeypatch):
    body = workspace.WorkspaceExecuteInput(
        task="document",
        format="pdf",
        document_count=2,
        document_style="official",
        title="RevelaCode Institutional Documents",
        prompt="Prepare an institutional introduction and a separate collaboration proposal.",
        official_metadata={"organization": "RevelaCode Software Solutions", "date": "12 November 2026"},
    )
    payload = {
        "documents": [
            {
                "title": "Institutional Introduction",
                "official_metadata": {"subject": "Institutional introduction"},
                "sections": [{"heading": "Overview", "level": 1, "paragraphs": ["Introduction text."]}],
            },
            {
                "title": "Collaboration Proposal",
                "official_metadata": {"subject": "Collaboration proposal"},
                "sections": [{"heading": "Proposal", "level": 1, "paragraphs": ["Proposal text."]}],
            },
        ]
    }
    monkeypatch.setattr(
        workspace,
        "_model_text",
        lambda *args, **kwargs: (json.dumps(payload), {"provider": "test", "model": "fixture"}),
    )
    documents, provider = workspace._multiple_document_payload(body, "RevelaCode", 2)
    assert [item["title"] for item in documents] == ["Institutional Introduction", "Collaboration Proposal"]
    assert all(item["official_metadata"]["organization"] == "RevelaCode Software Solutions" for item in documents)
    assert all(item["official_metadata"]["date"] == "12 November 2026" for item in documents)
    assert provider["provider"] == "test"


def test_multiple_document_payload_rejects_partial_model_response(monkeypatch):
    body = workspace.WorkspaceExecuteInput(
        task="document", format="pdf", document_count=2,
        prompt="Make two separate PDF documents.",
    )
    payload = {"documents": [{
        "title": "Only one",
        "sections": [{"heading": "Body", "paragraphs": ["Content"]}],
    }]}
    monkeypatch.setattr(workspace, "_model_text", lambda *args, **kwargs: (json.dumps(payload), {}))
    with pytest.raises(Exception, match="exactly 2 separate documents"):
        workspace._multiple_document_payload(body, "Document", 2)


def test_workspace_document_count_is_bounded():
    with pytest.raises(ValueError):
        workspace.WorkspaceExecuteInput(task="document", prompt="Create documents", document_count=5)
