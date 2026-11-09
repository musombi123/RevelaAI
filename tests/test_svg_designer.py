import xml.etree.ElementTree as ET

from ai import svg_designer


def test_standard_svg_namespace_is_not_treated_as_external_reference():
    source = (
        '<svg xmlns="http://www.w3.org/2000/svg" '
        'viewBox="0 0 1024 1024">'
        '<circle cx="512" cy="512" r="120" fill="#2563EB"/>'
        '</svg>'
    )

    result = svg_designer.sanitize_svg(source)
    root = ET.fromstring(result)

    assert root.tag == "svg"
    assert root.attrib["xmlns"] == svg_designer.SVG_NAMESPACE
    assert root.attrib["viewBox"] == svg_designer.ROOT_VIEWBOX


def test_external_svg_references_are_removed_without_weakening_validation():
    source = (
        '<svg xmlns="http://www.w3.org/2000/svg" '
        'viewBox="0 0 1024 1024">'
        '<path href="https://attacker.example/remote.svg#payload" d="M0 0"/>'
        '<rect style="fill:url(https://attacker.example/paint.svg#paint)"/>'
        '</svg>'
    )

    result = svg_designer.sanitize_svg(source)
    root = ET.fromstring(result)

    assert all(
        not any(svg_designer._local_name(key).lower() in {"href", "src", "style"} for key in node.attrib)
        for node in root.iter()
    )


def test_local_deterministic_fallback_produces_valid_svg():
    result = svg_designer._local_svg_fallback(
        {"request": "Create a modern technology logo"},
        text="RevelaAI",
    )
    root = ET.fromstring(result)

    assert root.tag == "svg"
    assert root.attrib["xmlns"] == svg_designer.SVG_NAMESPACE
    svg_designer._validate_svg(root, expected_text="RevelaAI")


def test_generate_svg_uses_local_fallback_when_provider_is_unavailable(monkeypatch):
    monkeypatch.setattr(
        svg_designer,
        "ask_hf",
        lambda **kwargs: {
            "success": False,
            "error": "Gemini provider timed out",
            "error_code": "gemini_timeout",
        },
    )

    result = svg_designer.generate_svg(
        {"request": "Create a software logo"},
        text="RevelaAI",
    )

    root = ET.fromstring(result)
    svg_designer._validate_svg(root, expected_text="RevelaAI")
