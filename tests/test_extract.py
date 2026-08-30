import json, unittest, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from extract import apply_pricing

class TestPricing(unittest.TestCase):
    def test_override_basic(self):
        sessions=[{"model": json.dumps({"providerID":"opencode","id":"big-pickle"}), "tokens_input":1_000_000, "tokens_output":500_000, "tokens_cache_read":0, "tokens_cache_write":0, "tokens_reasoning":0, "cost":999}]
        pricing={"models":{"opencode/big-pickle":{"input_per_1M":2.5,"output_per_1M":10}}}
        total, models = apply_pricing(sessions, pricing)
        self.assertAlmostEqual(sessions[0]["cost"], 2.5+5.0)
        self.assertEqual(sessions[0]["cost_source"],"pricing")

    def test_reasoning_priced(self):
        sessions=[{"model": json.dumps({"providerID":"opencode","id":"m"}), "tokens_input":0,"tokens_output":0,"tokens_cache_read":0,"tokens_cache_write":0,"tokens_reasoning":1_000_000,"cost":0}]
        pricing={"models":{"opencode/m":{"reasoning_per_1M":3.0}}}
        apply_pricing(sessions, pricing)
        self.assertAlmostEqual(sessions[0]["cost"], 3.0)

    def test_fallback_opencode(self):
        sessions=[{"model": json.dumps({"providerID":"x","id":"y"}), "cost":1.23, "tokens_input":0,"tokens_output":0,"tokens_cache_read":0,"tokens_cache_write":0,"tokens_reasoning":0}]
        apply_pricing(sessions, {"models":{}})
        self.assertEqual(sessions[0]["cost"], 1.23)
        self.assertEqual(sessions[0]["cost_source"],"opencode")

    def test_validation_negative(self):
        sessions=[{"model": json.dumps({"providerID":"opencode","id":"m"}), "tokens_input":1_000_000,"cost":0,"tokens_output":0,"tokens_cache_read":0,"tokens_cache_write":0,"tokens_reasoning":0}]
        pricing={"models":{"opencode/m":{"input_per_1M":-5,"output_per_1M":"bad"}}}
        apply_pricing(sessions, pricing)
        # -5 -> 0, bad -> ignoré => coût 0
        self.assertEqual(sessions[0]["cost"], 0)

if __name__=="__main__":
    unittest.main()
