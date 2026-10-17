import unittest
from revelai.core.agi_manifest import AGI_MANIFEST, get_manifest, get_status_summary
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
if __name__=="__main__": unittest.main()
