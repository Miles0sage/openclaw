import unittest
import sys
import os

# Add the parent directory to the system path to allow importing cost_tracker
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from cost_tracker import calculate_cost

class TestCalculateCost(unittest.TestCase):

    def test_basic_cost_calculation(self):
        # Test with a known model and token counts
        # claude-opus-4-6: input 15.0/M, output 75.0/M
        model = "claude-opus-4-6"
        tokens_input = 100000
        tokens_output = 200000
        expected_cost = (100000 * 15.0 + 200000 * 75.0) / 1_000_000
        self.assertAlmostEqual(calculate_cost(model, tokens_input, tokens_output), expected_cost, places=6)

    def test_default_pricing_fallback(self):
        # Test with an unknown model to ensure default pricing is used
        # _DEFAULT_PRICING: input 3.0/M, output 15.0/M
        model = "unknown-model"
        tokens_input = 50000
        tokens_output = 100000
        expected_cost = (50000 * 3.0 + 100000 * 15.0) / 1_000_000
        self.assertAlmostEqual(calculate_cost(model, tokens_input, tokens_output), expected_cost, places=6)

    def test_zero_tokens(self):
        # Test with zero input and output tokens
        model = "claude-haiku-4-5-20251001"
        tokens_input = 0
        tokens_output = 0
        expected_cost = 0.0
        self.assertEqual(calculate_cost(model, tokens_input, tokens_output), expected_cost)

if __name__ == '__main__':
    unittest.main()
