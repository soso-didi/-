import unittest

from backend.engine import CalculationError, evaluate_expression, evaluate_rule, interpolate


class EngineTests(unittest.TestCase):
    def test_safe_expression_and_math(self):
        self.assertAlmostEqual(evaluate_expression("Fx / n + sqrt(9)", {"Fx": 100, "n": 4}), 28)
        with self.assertRaises(CalculationError): evaluate_expression("__import__('os').system('whoami')", {})

    def test_condition_and_interpolation_boundaries(self):
        rule = {"kind":"expression", "expression":"x / n", "conditions":[{"expression":"n > 0"}]}
        self.assertEqual(evaluate_rule(rule, {"x": 10, "n": 2}).value, 5)
        with self.assertRaises(CalculationError): evaluate_rule(rule, {"x": 10, "n": 0})
        rows=[{"x":0,"y":0},{"x":10,"y":20}]
        self.assertEqual(interpolate(rows,"x","y",5),10)
        with self.assertRaises(CalculationError): interpolate(rows,"x","y",11)


if __name__ == "__main__": unittest.main()
