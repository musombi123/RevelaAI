from PIL import Image

from services import design_studio


def _plan():
    return {"kind": "poster", "aspect_ratio": "1:1", "palette": []}


def test_model_design_brief_preserves_exact_user_copy(monkeypatch):
    monkeypatch.setattr(design_studio, "ask_hf", lambda *args, **kwargs: {
        "success": True,
        "response": '{"layout":"asymmetric editorial","palette":["#123456"],"hierarchy":{"title_scale":1.4},"title":"MODEL CHANGED THIS"}',
    })
    brief = design_studio.build_design_brief(
        'Create a poster saying "Youth Conference 2026"',
        _plan(),
        {"aspect_ratio": "1:1"},
    )
    assert brief["title"] == "Youth Conference 2026"
    assert brief["title_scale"] == 1.4
    assert brief["palette"] == ["#123456"]
    assert brief["brief_source"] == "configured_text_model"


def test_all_eight_design_templates_render_crisp_raster_assets(monkeypatch):
    monkeypatch.setattr(design_studio, "ask_hf", lambda *args, **kwargs: {"success": False})
    for template in sorted(design_studio.TEMPLATES):
        brief = design_studio.build_design_brief(
            'Create a design saying "RevelaCode" with "Code. Innovate. Transform."',
            _plan(),
            {"template": template, "aspect_ratio": "1:1"},
        )
        brief["width"] = 360
        brief["height"] = 360
        image = design_studio.render_design(brief)
        assert isinstance(image, Image.Image)
        assert image.size == (360, 360)
        assert image.mode == "RGB"
        assert brief["title"] == "RevelaCode"


def test_revision_can_change_palette_and_title_hierarchy(monkeypatch):
    monkeypatch.setattr(design_studio, "ask_hf", lambda *args, **kwargs: {"success": False})
    brief = design_studio.build_design_brief(
        'Create a poster saying "Launch Day"',
        _plan(),
        {"revision": "change colour to green and make the title bigger"},
    )
    assert brief["palette"][0] == design_studio.COLORS["green"]
    assert brief["title_scale"] == 1.55
