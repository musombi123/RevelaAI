from PIL import Image

from services import image_service


def test_design_generation_exports_png_jpg_pdf_and_stable_public_urls(monkeypatch, tmp_path):
    monkeypatch.setattr(image_service, "IMAGE_DIR", str(tmp_path))
    monkeypatch.setattr(image_service, "build_image_prompt", lambda _request: {
        "kind": "poster", "aspect_ratio": "1:1", "palette": [], "prompt": "poster",
        "negative_prompt": None, "has_text": True, "engine": "image",
    })
    monkeypatch.setattr(image_service, "build_design_brief", lambda *args, **kwargs: {
        "template": "poster", "width": 320, "height": 320, "title": "Test",
        "palette": ["#0A74DA"], "safe_margin": 0.08, "title_scale": 1.2,
    })
    monkeypatch.setattr(image_service, "render_design", lambda brief: Image.new("RGB", (brief["width"], brief["height"]), "white"))

    result = image_service.generate_image_asset(
        "Create a poster saying Test",
        request_base_url="https://revelaai.example",
    )

    assert result["asset_type"] == "png"
    assert set(result["downloads"]) == {"png", "jpg", "pdf"}
    assert result["image_url"].endswith(".png")
    assert all(url.startswith("https://revelaai.example/ai/images/revelaai_") for url in result["downloads"].values())
    assert all((tmp_path / url.rsplit("/", 1)[-1]).is_file() for url in result["downloads"].values())


def test_image_options_accept_supported_ratios_and_full_seed_range():
    options = image_service.parse_image_options({
        "aspect_ratio": "A4",
        "output_format": "pdf",
        "template": "whatsapp_status",
        "seed": 4_000_000_000,
    })
    assert options["aspect_ratio"] == "a4"
    assert options["output_format"] == "pdf"
    assert options["template"] == "whatsapp_status"
    assert options["seed"] == 4_000_000_000
