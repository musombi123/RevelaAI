"""Premium automation operations must be denied before planning/execution."""
from fastapi.responses import JSONResponse

from fastapi_routes import automation_fabric as routes


def test_automation_planning_rejects_missing_entitlement_before_creating_plan(monkeypatch, tmp_path):
    denied = JSONResponse(
        {"status": "error", "code": "premium_entitlement_required"},
        status_code=402,
    )
    monkeypatch.setattr(routes, "_principal", lambda headers: ("user:acct-1", None))
    monkeypatch.setattr(routes, "_automation_entitlement", lambda headers: denied)
    monkeypatch.setattr(
        routes,
        "create_plan",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("automation plans must not be created without entitlement")
        ),
    )

    result = routes._plan(
        {"authorization": "Bearer test-token"},
        {"steps": [{"tool": "math.evaluate", "args": {"expression": "1 + 1"}}]},
    )

    assert result is denied
    assert result.status_code == 402


def test_automation_execution_rejects_missing_entitlement_before_execution(monkeypatch):
    denied = JSONResponse(
        {"status": "error", "code": "premium_entitlement_required"},
        status_code=402,
    )
    monkeypatch.setattr(routes, "_principal", lambda headers: ("user:acct-1", None))
    monkeypatch.setattr(routes, "_automation_entitlement", lambda headers: denied)
    monkeypatch.setattr(
        routes,
        "execute_plan",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("execution must not begin without entitlement")
        ),
    )

    result = routes._execute(
        {"authorization": "Bearer test-token"},
        {"plan_id": "plan-1", "plan_hash": "a" * 64, "approved": True},
    )

    assert result is denied
    assert result.status_code == 402
