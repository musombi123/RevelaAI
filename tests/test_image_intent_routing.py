from services.ai_service import detect_capability


def test_canva_style_artifact_requests_route_to_image_generation():
    requests = [
        "I need an Instagram post for the launch",
        "Make a WhatsApp status for the event",
        "Design a business card for my company",
        "Create an invitation for a graduation",
        "Design a certificate for the winner",
        "Make an Instagram story for the campaign",
    ]
    for request in requests:
        assert detect_capability(request) == "image_generation", request


def test_normal_text_request_does_not_enter_the_design_router():
    assert detect_capability("Explain the difference between SVG and PNG.") == "text"
