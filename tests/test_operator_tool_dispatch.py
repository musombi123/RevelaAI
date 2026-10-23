"""Regression tests for explicit, approval-gated operator tool dispatch."""
import unittest
from unittest.mock import patch

from fastapi.responses import JSONResponse

from ai.operator_tool_dispatch import (
    classify_operator_tool_request,
    dispatch_operator_tool,
)


class OperatorToolDispatchTests(unittest.TestCase):
    def test_explanatory_questions_stay_in_normal_chat(self):
        self.assertIsNone(classify_operator_tool_request("How does Sci Defend protect a website?"))
        self.assertIsNone(classify_operator_tool_request("Explain Meta Engineer's architecture"))
        self.assertIsNone(classify_operator_tool_request("Run a general code review"))

    def test_explicit_actions_route_to_correct_tool(self):
        self.assertEqual(
            classify_operator_tool_request("Run the Sci Defend shield scan now"),
            {"tool": "sci-defend", "operation": "shield_scan"},
        )
        self.assertEqual(
            classify_operator_tool_request("Meta Engineer: scan architecture"),
            {"tool": "meta-engineer", "operation": "architecture_scan"},
        )
        self.assertEqual(
            classify_operator_tool_request("Meta Engineer: propose safer API boundaries for the user dashboard"),
            {"tool": "meta-engineer", "operation": "proposal"},
        )

    @patch("fastapi_routes.admin_auth.require_platform_admin")
    def test_sci_scan_fails_closed_for_non_admin(self, require_admin):
        require_admin.return_value = (
            None,
            JSONResponse({"status": "error", "code": "admin_required"}, status_code=403),
        )
        result = dispatch_operator_tool(
            "Run the Sci Defend shield scan now",
            authorization="Bearer user-token",
        )
        self.assertEqual(result["operator_tool"]["status"], "blocked")
        self.assertFalse(result["operator_tool"]["invoked"])
        self.assertFalse(result["operator_tool"]["executed"])
        require_admin.assert_called_once()

    @patch("fastapi_routes.admin_auth.require_platform_admin")
    @patch("fastapi_routes.meta_engineer._scan")
    def test_meta_architecture_scan_invokes_read_only_tool(self, scan, require_admin):
        require_admin.return_value = ("canonical-admin-id", None)
        scan.return_value = {
            "status": "ok",
            "module_count": 11,
            "free_slots": ["tests"],
            "read_only": True,
        }
        result = dispatch_operator_tool(
            "Meta Engineer: scan architecture",
            authorization="Bearer verified-admin-token",
        )
        scan.assert_called_once_with()
        self.assertEqual(result["operator_tool"]["status"], "completed")
        self.assertTrue(result["operator_tool"]["invoked"])
        self.assertTrue(result["operator_tool"]["executed"])
        self.assertFalse(result["operator_tool"]["safety"]["target_mutation_performed"])

    @patch("fastapi_routes.admin_auth.require_platform_admin")
    @patch("ai.core_mesh.get_core_mesh_dashboard")
    @patch("ai.usect_zero_tools.execute_tool")
    @patch("fastapi_routes.sci_core._shield_scan")
    @patch("fastapi_routes.meta_engineer._scan")
    def test_guardian_sweep_runs_live_components_and_reports_partial_health(
        self, meta_scan, sci_scan, zero_tool, mesh, require_admin
    ):
        require_admin.return_value = ("canonical-admin-id", None)
        mesh.return_value = {
            "status": "partial",
            "cores": {
                "zero": {"status": "ok", "reachable": True},
                "one": {"status": "offline", "reachable": False},
                "two": {"status": "ok", "reachable": True},
            },
            "active_signed_tools_count": 2,
        }
        zero_tool.return_value = {
            "status": "success", "executed": True, "operation": "diagnostics",
            "result": {"write_ready": True},
        }
        sci_scan.return_value = {
            "status": "completed", "defensive_only": True,
            "threats_last_24h": 0, "shields_active": 1,
        }
        meta_scan.return_value = {
            "status": "ok", "module_count": 25,
            "free_slots": [], "read_only": True,
        }

        result = dispatch_operator_tool(
            "Run a full Guardian check across the RevelaCode ecosystem",
            authorization="Bearer verified-admin-token",
        )
        self.assertEqual(result["operator_tool"]["status"], "partial")
        self.assertTrue(result["operator_tool"]["executed"])
        components = result["operator_tool"]["result"]["components"]
        self.assertTrue(components["core_zero_diagnostics"]["ok"])
        self.assertTrue(components["sci_defend_scan"]["ok"])
        self.assertTrue(components["meta_engineer_scan"]["ok"])
        self.assertFalse(result["operator_tool"]["result"]["all_cores_reachable"])
        self.assertFalse(result["operator_tool"]["safety"]["target_mutation_performed"])
        mesh.assert_called_once_with(force_refresh=True)
        zero_tool.assert_called_once_with("diagnostics", {})
        sci_scan.assert_called_once_with()
        meta_scan.assert_called_once_with()

    @patch("fastapi_routes.admin_auth.require_platform_admin")
    @patch("fastapi_routes.meta_engineer._propose")
    def test_meta_proposal_is_not_misreported_as_production_execution(self, propose, require_admin):
        require_admin.return_value = ("canonical-admin-id", None)
        propose.return_value = JSONResponse(
            {"status": "awaiting_approval", "idea_id": "idea-123"},
            status_code=201,
        )
        result = dispatch_operator_tool(
            "Meta Engineer: propose safer API boundaries for the user dashboard",
            authorization="Bearer verified-admin-token",
        )
        propose.assert_called_once()
        self.assertEqual(result["operator_tool"]["status"], "proposal_created")
        self.assertTrue(result["operator_tool"]["proposal_created"])
        self.assertFalse(result["operator_tool"]["executed"])
        self.assertTrue(result["operator_tool"]["safety"]["human_approval_required"])
        self.assertFalse(result["operator_tool"]["safety"]["automatic_merge"])


if __name__ == "__main__":
    unittest.main()
