import unittest
from revelai.core.agi_manifest import AGI_MANIFEST, get_manifest, get_status_summary, get_self_description_answer
from revelai.routers.agi_router import agi_router

class AGIManifestTests(unittest.TestCase):
 def test_six_evolution_phases(self):
  self.assertEqual(len(AGI_MANIFEST["evolution_timeline"]),6)
 def test_required_capabilities_are_recorded(self):
  for key in ("vision","speech","research","defensive_security","disaster_management","hardware_prototyping","meta_engineering","memory"):
   self.assertIn(key,AGI_MANIFEST["capabilities"])
 def test_manifest_returns_defensive_copy(self):
  value=get_manifest(); value["identity"]["name"]="changed"
  self.assertEqual(AGI_MANIFEST["identity"]["name"],"RevelaAI")
 def test_status_does_not_claim_proven_agi_or_live_health(self):
  status=get_status_summary()
  self.assertFalse(status["scientifically_verified_agi"])
  self.assertFalse(status["live"])
 def test_router_declares_routes(self):
  self.assertGreaterEqual(len(agi_router.deferred_functions),2)
 def test_capabilities_question_uses_manifest_answer(self):
  answer=get_self_description_answer("What are your capabilities?")
  self.assertIn("six specialist hubs",answer)
  self.assertIn("conditional",answer.lower())
 def test_defensive_question_does_not_claim_total_protection(self):
  answer=get_self_description_answer("Can you defend the ecosystem from any virus or attack?")
  self.assertIn("cannot guarantee protection from every virus or attack",answer)
  self.assertIn("will not hack back",answer)
 def test_unrelated_request_is_not_intercepted(self):
  self.assertIsNone(get_self_description_answer("I want to build something"))
if __name__=="__main__": unittest.main()
