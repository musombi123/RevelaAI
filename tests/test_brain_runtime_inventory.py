from revelai.core.brain_os import capability_inventory


def test_inventory_covers_existing_python_cores_and_native_brain_services():
    result = capability_inventory()
    capabilities = result["capabilities"]
    for name in (
        "orchestrator",
        "global_brain_adapter",
        "text_provider_client",
        "core_mesh_adapter",
        "core_auditor",
        "core_billing",
        "core_evolve",
        "core_foundry",
        "core_inspector",
        "core_meter",
        "core_migrate",
        "core_seed",
        "core_uncopyable",
    ):
        assert capabilities[name]["implemented_in_source"] is True

    assert result["native_cores"]["core_zero"]["implemented_in_source"] is True
    assert result["native_cores"]["core_one_genesis"]["implemented_in_source"] is True
    assert result["native_cores"]["core_two_infinite_mind"]["implemented_in_source"] is True


def test_text_provider_inventory_does_not_assume_gemini_is_the_only_provider(monkeypatch):
    from ai import ai_client

    monkeypatch.setattr(ai_client, "get_text_provider_status", lambda: {
        "providers": {
            "gemini": {"enabled": False},
            "huggingface": {"enabled": True},
            "mvi": {"enabled": False},
        },
        "gemini_model_validation": {"reachable": False, "model_valid": False},
    })

    result = capability_inventory()
    provider = result["capabilities"]["text_provider"]

    assert provider["configured"] is True
    assert provider["enabled_providers"] == ["huggingface"]
