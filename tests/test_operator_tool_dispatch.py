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
