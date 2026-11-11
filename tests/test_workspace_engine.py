import base64
import io

import pytest
from PIL import Image

from services.workspace_engine import (
    analyze_dataset, edit_image, extract_code_block, markdown_to_sections,
    markdown_to_slides, parse_dataset,
)


def test_dataset_analysis_profiles_numeric_categorical_missing_and_duplicates():
    result = analyze_dataset({
        "headers": ["amount", "region"],
        "rows": [["10", "KE"], ["20", "UG"], ["10", "KE"], ["", "TZ"]],
    })
    assert result["row_count"] == 4
    assert result["column_count"] == 2
    assert result["duplicate_rows"] == 1
    assert result["missing_cells"] == 1
    assert result["completeness_pct"] == 87.5
    amount, region = result["columns"]
    assert amount["type"] == "numeric"
    assert amount["statistics"]["mean"] == pytest.approx(13.333333)
    assert region["type"] == "categorical"
    assert region["top_values"][0] == {"value": "KE", "count": 2}
    assert len(result["workbook_payload"]["sheets"]) == 5


def test_dataset_parser_accepts_csv_and_rejects_duplicate_headers():
    headers, rows = parse_dataset("name,value\nAlpha,10\nBeta,20\n")
    assert headers == ["name", "value"]
    assert rows == [["Alpha", "10"], ["Beta", "20"]]
    with pytest.raises(ValueError, match="unique"):
        parse_dataset({"headers": ["Amount", "amount"], "rows": [[1, 2]]})


def test_dataset_parser_enforces_row_and_column_bounds():
    with pytest.raises(ValueError, match="at most"):
        parse_dataset({"headers": ["a"], "rows": [["1"]] * 10_001})


def test_python_code_artifact_is_parsed_and_invalid_source_is_rejected():
    fence = chr(96) * 3
    response = "Implementation:\n" + fence + "python\ndef add(a, b):\n    return a + b\n" + fence
    code, extension, mime, validation = extract_code_block(response)
    assert "def add" in code
    assert extension == ".py"
    assert mime == "text/x-python"
    assert validation == "python_ast"
    invalid = fence + "python\ndef broken(:\n    pass\n" + fence
    with pytest.raises(ValueError, match="syntax validation"):
        extract_code_block(invalid)


def test_html_code_artifact_is_extracted_for_ui_prototypes():
    fence = chr(96) * 3
    html = '<!doctype html><html><head><meta name="viewport" content="width=device-width"></head><body><main>Ready</main></body></html>'
    code, extension, mime, validation = extract_code_block(fence + "html\n" + html + "\n" + fence)
    assert code.strip() == html
    assert extension == ".html"
    assert mime == "text/html"
    assert validation == "not_available"


def test_json_code_artifact_is_parsed():
    fence = chr(96) * 3
    code, extension, mime, validation = extract_code_block(fence + 'json\n{"ok": true}\n' + fence)
    assert code.strip() == '{"ok": true}'
    assert extension == ".json"
    assert mime == "application/json"
    assert validation == "json_parse"


def test_markdown_is_converted_to_editable_document_and_slides():
    sections = markdown_to_sections("# Overview\nFirst paragraph.\n- One point\n\n## Detail\nSecond paragraph.")
    assert [item["heading"] for item in sections] == ["Overview", "Detail"]
    assert sections[0]["paragraphs"] == ["First paragraph.", "• One point"]
    slides = markdown_to_slides("# Overview\n- First\n- Second\n## Detail\nSupporting detail.", "Deck")
    assert [item["title"] for item in slides] == ["Overview", "Detail"]
    assert slides[0]["bullets"] == ["First", "Second"]


def test_image_edit_applies_bounded_operations_without_persisting_original():
    source = Image.new("RGB", (20, 10), (120, 80, 40))
    buffer = io.BytesIO()
    source.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    output, width, height = edit_image(
        encoded, "image/png",
        [{"type": "crop", "left": 0.0, "top": 0.0, "right": 0.5, "bottom": 1.0},
         {"type": "grayscale"}],
    )
    assert (width, height) == (10, 10)
    with Image.open(io.BytesIO(output)) as edited:
        assert edited.format == "PNG"
        assert edited.size == (10, 10)
        assert edited.mode == "RGBA"


def test_image_edit_rejects_unsupported_operations_and_mime_mismatch():
    source = Image.new("RGB", (2, 2), (0, 0, 0))
    buffer = io.BytesIO()
    source.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    with pytest.raises(ValueError, match="Unsupported"):
        edit_image(encoded, "image/png", [{"type": "execute"}])
    with pytest.raises(ValueError, match="MIME"):
        edit_image(encoded, "image/jpeg", [])
