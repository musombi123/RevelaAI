"""Sci-Core safety and native FastAPI route-contract tests."""
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from revelai.sci_core.research_engine import ResearchPolicyViolation

from asgi import app
from fastapi_routes.sci_core import router as sci_router
from revelai.sci_core.research_engine import is_offensive_query, _summarize
from revelai.sci_core.hardware_lab import build_prototype
from revelai.sci_core.disaster_manager import simulate
from revelai.sci_core import ip_guard

client = TestClient(app)


class SciCoreSafetyTests(unittest.TestCase):
    def test_offensive_query_is_blocked(self):
        with self.assertRaises(ResearchPolicyViolation):
            is_offensive_query("how to hack into a server")

    def test_civilian_research_query_allowed(self):
        self.assertFalse(is_offensive_query("ESP32 water pump automation"))

    def test_local_summary_is_bounded_and_nonempty(self):
        value = _summarize(
            "ESP32 sensors measure soil moisture. Soil moisture sensors support "
            "irrigation decisions. A controller can send readings over Wi-Fi."
        )
        self.assertTrue(value)
        self.assertLessEqual(len(value), 3500)

    def test_hardware_prototype_is_never_executed(self):
        fake_collection = type(
            "Collection",
            (),
            {"insert_one": lambda self, doc: None},
        )()
        with patch("revelai.sci_core.hardware_lab.collection", return_value=fake_collection):
            result = build_prototype(
                "electronics", "Build a soil moisture sensor for irrigation"
            )
        self.assertFalse(result["executed"])
        self.assertIn("firmware.cpp", result["artifacts"])
        self.assertIn("safety.md", result["artifacts"])

    def test_browser_cors_preflight_is_allowed_without_bearer_token(self):
        with patch("fastapi_routes.sci_core.require_platform_admin") as admin_check:
            response = client.options(
                "/api/sci/shield/status",
                headers={
                    "Origin": "https://revelacode-frontend.onrender.com",
                    "Access-Control-Request-Method": "GET",
                    "Access-Control-Request-Headers": "authorization",
                },
            )
        self.assertIn(response.status_code, (200, 204))
        self.assertEqual(
            response.headers.get("Access-Control-Allow-Origin"),
            "https://revelacode-frontend.onrender.com",
        )
        self.assertIn(
            "authorization",
            (response.headers.get("Access-Control-Allow-Headers") or "").lower(),
        )
        admin_check.assert_not_called()

    def test_actual_sci_core_request_remains_admin_protected(self):
        with patch(
            "fastapi_routes.sci_core.require_platform_admin",
            return_value=(
                None,
                JSONResponse({"status": "error", "code": "admin_required"}, status_code=403),
            ),
        ) as admin_check:
            response = client.get("/api/sci/shield/status")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "admin_required")
        admin_check.assert_called_once()

    def test_routes_are_registered(self):
        self.assertGreater(len(sci_router.routes), 0)

    def test_disaster_type_is_validated(self):
        with self.assertRaises(ValueError):
            simulate("disable_security")


class _FakeCursor:
    def __init__(self, rows):
        self.rows = list(rows)

    def sort(self, field, direction=-1):
        self.rows.sort(key=lambda row: row.get(field) or datetime.min.replace(tzinfo=timezone.utc), reverse=direction < 0)
        return self

    def limit(self, count):
        self.rows = self.rows[:count]
        return self

    def __iter__(self):
        return iter(self.rows)


class _FakeCollection:
    def __init__(self):
        self.rows = []

    def create_index(self, *args, **kwargs):
        return "index"

    def insert_one(self, document):
        self.rows.append(dict(document))
        return type("InsertResult", (), {"inserted_id": len(self.rows)})()

    def _matches(self, row, query):
        for key, expected in (query or {}).items():
            value = row.get(key)
            if isinstance(expected, dict) and "$gte" in expected:
                if value is None or value < expected["$gte"]:
                    return False
            elif value != expected:
                return False
        return True

    def count_documents(self, query=None):
        return sum(1 for row in self.rows if self._matches(row, query or {}))

    def find(self, query=None):
        return _FakeCursor([row.copy() for row in self.rows if self._matches(row, query or {})])

    def find_one(self, query=None, sort=None):
        rows = [row for row in self.rows if self._matches(row, query or {})]
        if not rows:
            return None
        if sort:
            field, direction = sort[0]
            rows.sort(key=lambda row: row.get(field) or datetime.min.replace(tzinfo=timezone.utc), reverse=direction < 0)
        return rows[0].copy()

    def update_one(self, query, update, upsert=False):
        for row in self.rows:
            if self._matches(row, query):
                row.update(update.get("$set", {}))
                return type("UpdateResult", (), {"modified_count": 1, "upserted_id": None})()
        if upsert:
            row = dict(query)
            row.update(update.get("$set", {}))
            self.rows.append(row)
            return type("UpdateResult", (), {"modified_count": 0, "upserted_id": len(self.rows)})()
        return type("UpdateResult", (), {"modified_count": 0, "upserted_id": None})()

    def update_many(self, query, update):
        count = 0
        for row in self.rows:
            if self._matches(row, query):
                row.update(update.get("$set", {}))
                count += 1
        return type("UpdateResult", (), {"modified_count": count})()


class _FakeDatabase:
    def __init__(self):
        self.collections = {}

    def __getitem__(self, name):
        return self.collections.setdefault(name, _FakeCollection())

    def command(self, name):
        return {"ok": 1}


class SciCoreIPGuardTests(unittest.TestCase):
    def test_resolver_does_not_trust_unconfigured_forwarding_headers(self):
        headers = {
            "x-forwarded-for": "1.1.1.1",
            "x-real-ip": "8.8.8.8",
        }
        with patch.dict(os.environ, {
            "REVELAAI_TRUST_PROXY_HEADERS": "",
            "REVELAAI_TRUST_CLOUDFLARE_IP_HEADER": "",
        }, clear=False):
            self.assertEqual(
                ip_guard.client_ip_from_headers(headers, "10.0.0.8"),
                None,
            )

    def test_resolver_uses_configured_cloudflare_client_ip(self):
        headers = {"cf-connecting-ip": "1.1.1.1", "x-forwarded-for": "8.8.8.8"}
        with patch.dict(os.environ, {"REVELAAI_TRUST_CLOUDFLARE_IP_HEADER": "true"}, clear=False):
            self.assertEqual(
                ip_guard.client_ip_from_headers(headers, "10.0.0.8"),
                "1.1.1.1",
            )

    def test_only_exact_public_ip_addresses_are_accepted(self):
        for value in ("10.0.0.1", "127.0.0.1", "192.0.2.10", "1.1.1.0/24", "not-an-ip"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    ip_guard._parse_ip(value)
        self.assertEqual(ip_guard._parse_ip("1.1.1.1"), "1.1.1.1")

    def test_manual_block_is_persistent_audited_and_enforced_by_lookup(self):
        database = _FakeDatabase()
        with patch.object(ip_guard, "_mongo_db", return_value=database), patch.dict(
            os.environ, {"SCI_CORE_IP_ALLOWLIST": ""}, clear=False
        ):
            result = ip_guard.block_ip(
                "1.1.1.1",
                actor="admin-123",
                reason="Repeated suspicious application requests",
                duration_minutes=30,
                current_ip="8.8.8.8",
            )
            self.assertEqual(result["status"], "blocked")
            self.assertIsNotNone(ip_guard.is_ip_blocked("1.1.1.1"))
            self.assertEqual(database["sci_ip_block_events"].count_documents({"action": "blocked"}), 1)

    def test_admin_cannot_block_own_session_ip(self):
        database = _FakeDatabase()
        with patch.object(ip_guard, "_mongo_db", return_value=database), patch.dict(
            os.environ, {"SCI_CORE_IP_ALLOWLIST": ""}, clear=False
        ):
            with self.assertRaisesRegex(ValueError, "cannot block the IP address used"):
                ip_guard.block_ip(
                    "1.1.1.1",
                    actor="admin-123",
                    reason="Repeated suspicious application requests",
                    current_ip="1.1.1.1",
                )

    def test_allowlisted_ip_cannot_be_manually_blocked(self):
        database = _FakeDatabase()
        with patch.object(ip_guard, "_mongo_db", return_value=database), patch.dict(
            os.environ, {"SCI_CORE_IP_ALLOWLIST": "1.1.1.0/24"}, clear=False
        ):
            with self.assertRaisesRegex(ValueError, "protected by the administrator IP allowlist"):
                ip_guard.block_ip(
                    "1.1.1.1",
                    actor="admin-123",
                    reason="Repeated suspicious application requests",
                )

    def test_repeated_failed_authentication_creates_a_timed_block(self):
        database = _FakeDatabase()
        with patch.object(ip_guard, "_mongo_db", return_value=database), patch.object(
            ip_guard, "_AUTO_BLOCK_THRESHOLD", 2
        ), patch.dict(os.environ, {"SCI_CORE_IP_ALLOWLIST": ""}, clear=False):
            first = ip_guard.record_failed_authentication("1.1.1.1", "/api/auth/login")
            second = ip_guard.record_failed_authentication("1.1.1.1", "/api/auth/login")
            self.assertIsNone(first)
            self.assertEqual(second["status"], "blocked")
            self.assertEqual(second["source"], "auto_bruteforce")
            self.assertEqual(database["sci_auth_failures"].count_documents({"ip": "1.1.1.1"}), 2)

    def test_failed_non_auth_request_never_triggers_automatic_ip_block(self):
        with patch.object(ip_guard, "_mongo_db") as database:
            result = ip_guard.record_failed_authentication("1.1.1.1", "/api/sci/shield/status")
        self.assertIsNone(result)
        database.assert_not_called()

    def test_ip_guard_status_endpoint_is_admin_protected(self):
        with patch(
            "fastapi_routes.sci_core.require_platform_admin",
            return_value=(None, JSONResponse({"status": "error", "code": "admin_required"}, status_code=403)),
        ):
            response = client.get("/api/sci/ip-guard/status")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "admin_required")

    def test_block_endpoint_requires_explicit_confirmation(self):
        with patch("fastapi_routes.sci_core.require_platform_admin", return_value=("admin-123", None)):
            response = client.post(
                "/api/sci/ip-guard/block",
                json={"ip": "1.1.1.1", "reason": "Repeated suspicious requests", "confirm": False},
            )
        self.assertEqual(response.status_code, 400)
        self.assertIn("confirmation", response.json()["error"])


if __name__ == "__main__":
    unittest.main()
