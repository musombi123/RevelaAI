from urllib.parse import parse_qs, urlsplit
from io import BytesIO

from openpyxl import load_workbook
from docx import Document
from pptx import Presentation

from services.productivity_service import (
    create_powerpoint,
    create_spreadsheet,
    create_word_document,
    read_signed_file,
)


def _read_artifact(artifact):
    parts = urlsplit(artifact["download_url"])
    query = parse_qs(parts.query)
    return read_signed_file(
        artifact["file_id"],
        int(query["expires"][0]),
        query["sig"][0],
    )


def test_xlsx_contains_real_formula_and_opens(monkeypatch, tmp_path):
    monkeypatch.setenv("REVELAAI_PRODUCTIVITY_DIR", str(tmp_path))
    monkeypatch.setenv("REVELAAI_FILE_SIGNING_SECRET", "test-signing-secret-that-is-at-least-32-bytes")
    artifact = create_spreadsheet("user-1", {
        "title": "Finance model",
        "sheets": [{
            "name": "Summary",
            "headers": ["Amount", "Total"],
            "rows": [[10, None], [20, None], [None, "=SUM(A2:A3)"]],
        }],
    })
    path, _meta = _read_artifact(artifact)
    workbook = load_workbook(BytesIO(path.read_bytes()), data_only=False)
    assert workbook["Summary"]["B4"].value == "=SUM(A2:A3)"
    workbook.close()


def test_docx_and_pdf_preview_are_created(monkeypatch, tmp_path):
    monkeypatch.setenv("REVELAAI_PRODUCTIVITY_DIR", str(tmp_path))
    monkeypatch.setenv("REVELAAI_FILE_SIGNING_SECRET", "test-signing-secret-that-is-at-least-32-bytes")
    result = create_word_document("user-2", {
        "title": "Research Report",
        "sections": [{"heading": "Findings", "paragraphs": ["Evidence-based report."]}],
    })
    doc_path, _ = _read_artifact(result["primary"])
    assert Document(doc_path).paragraphs
    pdf_path, pdf_meta = _read_artifact(result["preview_file"])
    assert pdf_meta["mime_type"] == "application/pdf"
    assert pdf_path.read_bytes().startswith(b"%PDF")


def test_pptx_and_pdf_preview_are_created(monkeypatch, tmp_path):
    monkeypatch.setenv("REVELAAI_PRODUCTIVITY_DIR", str(tmp_path))
    monkeypatch.setenv("REVELAAI_FILE_SIGNING_SECRET", "test-signing-secret-that-is-at-least-32-bytes")
    result = create_powerpoint("user-3", {
        "title": "Demo",
        "slides": [{"title": "Overview", "bullets": ["One", "Two"]}],
    })
    pptx_path, _ = _read_artifact(result["primary"])
    assert len(Presentation(pptx_path).slides) == 1
    pdf_path, _ = _read_artifact(result["preview_file"])
    assert pdf_path.read_bytes().startswith(b"%PDF")
