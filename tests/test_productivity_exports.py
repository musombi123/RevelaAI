import base64
import pytest
from urllib.parse import parse_qs, urlsplit
from io import BytesIO

from openpyxl import load_workbook
from docx import Document
from pptx import Presentation
from PIL import Image

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



def _logo_image():
    buffer = BytesIO()
    Image.new("RGBA", (80, 40), (10, 116, 218, 220)).save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def test_official_docx_embeds_supplied_logo_and_formal_particulars(monkeypatch, tmp_path):
    monkeypatch.setenv("REVELAAI_PRODUCTIVITY_DIR", str(tmp_path))
    monkeypatch.setenv("REVELAAI_FILE_SIGNING_SECRET", "test-signing-secret-that-is-at-least-32-bytes")
    result = create_word_document("official-user", {
        "title": "Partnership Request",
        "document_style": "official",
        "official_metadata": {
            "document_type": "letter",
            "organization": "RevelaCode Software Solutions",
            "organization_address": ["Mombasa, Kenya"],
            "date": "11 November 2026",
            "recipient": "The Conference Secretary",
            "recipient_organization": "West Kenya Conference",
            "recipient_address": ["Kisumu, Kenya"],
            "subject": "Request for an institutional demonstration",
            "salutation": "Dear Conference Secretary,",
            "closing": "Yours faithfully,",
            "signatory": "Musombi William",
            "signatory_title": "Founder and Full-Stack Developer",
        },
        "sections": [{"heading": "Purpose", "paragraphs": ["We request an opportunity to demonstrate the platform."]}],
        "images": [{
            "image_base64": _logo_image(),
            "mime_type": "image/png",
            "alt_text": "RevelaCode logo",
            "placement": "header",
            "width_inches": 1.2,
        }],
    })
    doc_path, _ = _read_artifact(result["primary"])
    document = Document(doc_path)
    header_images = document.sections[0].header._element.xpath(".//wp:inline")
    assert len(header_images) == 1
    content = "\n".join(paragraph.text for paragraph in document.paragraphs)
    assert "West Kenya Conference" in content
    assert "REQUEST FOR AN INSTITUTIONAL DEMONSTRATION" in content
    assert "Musombi William" in content
    assert result["preview"]["images_embedded"] == 1
    pdf_path, _ = _read_artifact(result["preview_file"])
    assert pdf_path.read_bytes().startswith(b"%PDF")


def test_powerpoint_embeds_uploaded_logo_on_title_slide(monkeypatch, tmp_path):
    monkeypatch.setenv("REVELAAI_PRODUCTIVITY_DIR", str(tmp_path))
    monkeypatch.setenv("REVELAAI_FILE_SIGNING_SECRET", "test-signing-secret-that-is-at-least-32-bytes")
    result = create_powerpoint("slide-user", {
        "title": "RevelaCode Introduction",
        "slides": [{"title": "RevelaCode", "subtitle": "Code. Innovate. Transform."}],
        "images": [{
            "image_base64": _logo_image(),
            "mime_type": "image/png",
            "alt_text": "RevelaCode logo",
            "placement": "header",
            "width_inches": 1.1,
        }],
    })
    pptx_path, _ = _read_artifact(result["primary"])
    presentation = Presentation(pptx_path)
    pictures = [shape for shape in presentation.slides[0].shapes if shape.shape_type == 13]
    assert len(pictures) == 1
    assert result["preview"]["images_embedded"] == 1


def test_embedded_image_validation_rejects_invalid_image_bytes():
    from services.productivity_service import _decode_document_images

    with pytest.raises(ValueError, match="base64"):
        _decode_document_images(
            [{"image_base64": "not-base64", "mime_type": "image/png"}],
            allowed_placements={"header"},
        )
