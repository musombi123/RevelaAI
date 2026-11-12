from ai import core_mesh


def test_configuration_health_lists_names_without_secret_values(monkeypatch):
    monkeypatch.setenv("RENDER", "true")
    for name in (
        "USECT_ZERO_URL", "USECT_ZERO_BASE_URL", "USECT_ZERO_ADMIN_TOKEN",
        "USECT_ZERO_BRAIN_TOKEN", "USECT_ZERO_BRAIN_API_KEY",
        "GENESIS_BASE_URL", "GENESIS_ADMIN_TOKEN", "GENESIS_TOKEN",
        "GENESIS_ORCHESTRATOR_TOOLS_ENABLED", "MIND_BASE_URL",
        "MIND_ADMIN_TOKEN", "CORE_MESH_ADMIN_USER_IDS", "META_ENGINEER_ADMIN_USER_IDS",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(core_mesh, "_safe_fetch", lambda base, path, headers=None: {
        "status": "ok", "signing_key_configured": False
    } if path == "/v1/genesis/health" else {"status": "unavailable", "reason": "core_service_not_configured"})

    report = core_mesh.get_core_mesh_configuration_health()

    assert report["secrets_returned"] is False
    assert "USECT_ZERO_BRAIN_TOKEN" in report["missing_variable_names"]
    assert "GENESIS_BASE_URL" in report["missing_variable_names"]
    assert "GENESIS_SIGNING_KEY" in report["missing_variable_names"]
    serialized = str(report)
    assert "token-value" not in serialized
    assert all("configured" in item for item in report["items"])


def test_configuration_health_marks_unreachable_genesis_signing_state_unknown(monkeypatch):
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setattr(core_mesh, "_safe_fetch", lambda *args, **kwargs: {
        "status": "unavailable", "reason": "core_service_not_configured"
    })
    report = core_mesh.get_core_mesh_configuration_health()
    genesis = next(item for item in report["items"] if item["name"] == "GENESIS_SIGNING_KEY")
    assert genesis["unknown"] is True
    assert "GENESIS_SIGNING_KEY" in report["unknown_variable_names"]


def test_configuration_health_detects_a_genesis_token_rejected_by_the_core(monkeypatch):
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setenv("GENESIS_BASE_URL", "http://genesis-core-one:8781")
    monkeypatch.setenv("GENESIS_ADMIN_TOKEN", "test-only-not-a-real-secret")
    monkeypatch.setattr(core_mesh, "_safe_fetch", lambda base, path, headers=None: (
        {"status": "ok", "signing_key_configured": True}
        if path == "/v1/genesis/health"
        else {"reason": "upstream_http_401"}
    ))
    report = core_mesh.get_core_mesh_configuration_health()
    genesis = next(item for item in report["items"] if item["name"].startswith("GENESIS_ADMIN_TOKEN"))
    assert genesis["configured"] is True
    assert genesis["valid"] is False
    assert "rejected" in genesis["message"].lower()

def test_configuration_health_distinguishes_missing_private_routes_from_down_services(monkeypatch):
    monkeypatch.setenv("RENDER", "true")
    for name in ("USECT_ZERO_URL", "USECT_ZERO_BASE_URL", "GENESIS_BASE_URL", "MIND_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    report = core_mesh.get_core_mesh_configuration_health()
    assert report["core_probes"]["zero"]["reason"] == "core_service_not_configured"
    assert report["core_probes"]["genesis"]["reason"] == "core_service_not_configured"
    assert report["core_probes"]["mind"]["reason"] == "core_service_not_configured"
    assert all("Blueprint-linked HTTPS endpoint" in item["message"] for item in report["core_probes"].values())
    assert report["secrets_returned"] is False


def test_configuration_health_reports_service_down_when_private_url_exists(monkeypatch):
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setenv("USECT_ZERO_URL", "https://usect-zero-core-free.onrender.com")
    monkeypatch.setenv("GENESIS_BASE_URL", "https://genesis-core-one-free.onrender.com")
    monkeypatch.setenv("MIND_BASE_URL", "https://infinite-mind-core-free.onrender.com")
    monkeypatch.setattr(core_mesh, "_safe_fetch", lambda *args, **kwargs: {
        "status": "unavailable", "reachable": False, "reason": "core_service_unreachable"
    })
    report = core_mesh.get_core_mesh_configuration_health()
    assert all(probe["reason"] == "core_service_unreachable" for probe in report["core_probes"].values())
    assert all("waking from idle" in probe["message"] for probe in report["core_probes"].values())
