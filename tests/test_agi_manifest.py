import unittest

from revelai.core.agi_manifest import (
    AGI_MANIFEST,
    get_manifest,
    get_self_description_answer,
    get_status_summary,
)
from fastapi_routes.agi import router as agi_router


class AGIManifestTests(unittest.TestCase):
    def test_seven_evolution_phases_include_core_mesh(self):
        self.assertEqual(len(AGI_MANIFEST["evolution_timeline"]), 7)
        self.assertIn(
            "USECT Core Mesh",
            AGI_MANIFEST["evolution_timeline"][-1]["phase"],
        )

    def test_public_urls_and_static_status_are_truthful(self):
        identity = AGI_MANIFEST["identity"]
        self.assertEqual(identity["host"], "https://revelaai.onrender.com")
        self.assertEqual(
            identity["frontend"],
            "https://revelacode-frontend.onrender.com",
        )
        self.assertIn("source_manifest_only", identity["status"])
        self.assertNotIn("runtime_verified_by_status_endpoint", identity["status"])

    def test_required_capabilities_are_recorded(self):
        for key in (
            "vision",
            "speech",
            "research",
            "defensive_security",
            "disaster_management",
            "hardware_prototyping",
            "meta_engineering",
            "memory",
            "usect_zero",
            "genesis_core_one",
            "infinite_mind_core_two",
            "core_mesh",
        ):
            self.assertIn(key, AGI_MANIFEST["capabilities"])

    def test_core_mesh_does_not_claim_render_resources_are_live(self):
        deployment = AGI_MANIFEST["deployment"]
        self.assertEqual(deployment["public_gateway"], "RevelaAI")
        self.assertEqual(
            [service["name"] for service in deployment["private_services_declared_in_blueprint"]],
            ["usect-zero-core", "genesis-core-one", "infinite-mind-core"],
        )
        self.assertIn("desired resource", deployment["deployment_note"].lower())
        self.assertIn(
            "/api/usect-zero/health",
            AGI_MANIFEST["runtime_endpoints"]["usect_zero_health"],
        )

    def test_brain_os_evolution_capabilities_state_simulation_and_live_gates_truthfully(self):
        caps = AGI_MANIFEST["capabilities"]
        self.assertIn("recovery_policy", caps)
        self.assertIn("simulation_only", caps["recovery_policy"]["verification"])
        self.assertIn("defensive_monitoring", caps)
        self.assertIn(
            "requires REVELAAI_ALERT_WEBHOOK_URL",
            caps["defensive_monitoring"]["verification"],
        )
        self.assertIn("connector_contract", caps)
        self.assertIn("no live device", caps["connector_contract"]["verification"])
        self.assertIn("candidate_validation", caps)
        self.assertIn("unverified", caps["candidate_validation"]["verification"])

    def test_manifest_returns_defensive_copy(self):
        value = get_manifest()
        value["identity"]["name"] = "changed"
        self.assertEqual(AGI_MANIFEST["identity"]["name"], "RevelaAI")

    def test_status_reports_source_presence_not_live_health(self):
        status = get_status_summary()
        self.assertFalse(status["scientifically_verified_agi"])
        self.assertFalse(status["live"])
        self.assertFalse(status["deployment_health_checked"])
        self.assertIn("usect_zero_core", status["modules"])
        self.assertIn("genesis_core_one", status["modules"])
        self.assertIn("infinite_mind_core_two", status["modules"])
        self.assertEqual(status["modules_checked"], len(status["modules"]))

    def test_router_declares_routes(self):
        self.assertGreaterEqual(len(agi_router.routes), 2)

    def test_capabilities_question_uses_manifest_answer(self):
        answer = get_self_description_answer("What are your capabilities?")
        self.assertIn("six specialist hubs", answer)
        self.assertIn("source presence alone", answer.lower())
        self.assertIn("Core-Two", answer)

    def test_usect_zero_status_answer_does_not_assume_deployment(self):
        answer = get_self_description_answer("Is USECT-ZERO healthy?")
        self.assertIn("/api/usect-zero/health", answer)
        self.assertIn("do not prove", answer.lower())
        self.assertIn("usect-zero-core", answer)

    def test_defensive_question_does_not_claim_total_protection(self):
        answer = get_self_description_answer(
            "Can you defend the ecosystem from any virus or attack?"
        )
        self.assertIn("cannot guarantee protection from every virus or attack", answer)
        self.assertIn("will not hack back", answer)

    def test_unrelated_request_is_not_intercepted(self):
        self.assertIsNone(get_self_description_answer("I want to build something"))


if __name__ == "__main__":
    unittest.main()
