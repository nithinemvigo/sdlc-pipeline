"""Tests for pipeline_ui.usage."""
import unittest

import fixture_builder as fb
from pipeline_ui import usage


class UsageTest(unittest.TestCase):
    def test_dedupes_by_message_id(self):
        t = fb.Transcript()
        t.text(0, "a", message_id="m1", usage=fb.tokens(10, 5, cache_read=100, write_5m=20))
        t.text(0, "b", message_id="m1", usage=fb.tokens(10, 5, cache_read=100, write_5m=20))
        t.text(1, "c", message_id="m2", model="claude-haiku-5-5", usage=fb.tokens(1, 1, write_1h=8))
        by_model = usage.usage_by_model(fb.parsed(t))
        self.assertEqual(by_model["claude-opus-5-5"].to_dict(),
                         {"input": 10, "output": 5, "cache_write": 20, "cache_read": 100, "total": 135})
        self.assertEqual(by_model["claude-haiku-5-5"].cache_write_1h, 8)
        self.assertEqual(by_model["claude-haiku-5-5"].cache_write_5m, 0)

    def test_user_entries_ignored(self):
        t = fb.Transcript()
        t.user(0, "hi")
        self.assertEqual(usage.usage_by_model(fb.parsed(t)), {})

    def test_unsplit_cache_write_counts_as_5m(self):
        u = usage.usage_of({"input_tokens": 1, "output_tokens": 2, "cache_creation_input_tokens": 30})
        self.assertEqual((u.cache_write_5m, u.cache_write_1h), (30, 0))

    def test_cost_with_known_and_unknown_models(self):
        prices = {"claude-opus-5-5": {"input": 4, "output": 20, "cache_write_5m": 5, "cache_write_1h": 8,
                                      "cache_read": 0.2}}
        by_model = {
            "claude-opus-5-5": usage.Usage(input=1000000, output=100000, cache_write_1h=1000000, cache_read=1000000),
            "<synthetic>": usage.Usage(input=5),
        }
        cost, complete = usage.estimate_cost(by_model, prices)
        self.assertAlmostEqual(cost, 4 + 2 + 8 + 0.2)
        self.assertFalse(complete)
        self.assertEqual(usage.estimate_cost({"claude-opus-5-5": usage.Usage(input=1000000)}, prices), (4.0, True))

    def test_longest_prefix_price(self):
        prices = {"claude-opus-5": {"input": 5}, "claude-opus-5-5": {"input": 4}}
        self.assertEqual(usage.price_for("claude-opus-5-5", prices)["input"], 4)
        self.assertEqual(usage.price_for("claude-opus-5-5[1m]", prices)["input"], 4)
        self.assertEqual(usage.price_for("claude-opus-5-20260101", prices)["input"], 5)
        self.assertIsNone(usage.price_for("gpt-x", prices))

    def test_shipped_price_table(self):
        prices = usage.load_prices()
        for model in ("claude-fable-5-1", "claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5",
                      "claude-opus-4-8", "claude-sonnet-4-6", "claude-haiku-4-5"):
            self.assertEqual(set(prices[model]), {"input", "output", "cache_write_5m", "cache_write_1h", "cache_read"})
        self.assertEqual(prices["claude-opus-5-5"]["cache_read"], 0.20)
        self.assertEqual(prices["claude-fable-5-1"]["cache_read"], 0.25)

    def test_merge_does_not_mutate_inputs(self):
        a = {"m": usage.Usage(input=1)}
        b = {"m": usage.Usage(output=2), "n": usage.Usage(cache_read=3)}
        merged = usage.merge([a, b])
        self.assertEqual(usage.total(merged).total, 6)
        self.assertEqual(a["m"].output, 0)


if __name__ == "__main__":
    unittest.main()
