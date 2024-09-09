import unittest

from app.utilities.utilities import round_up_tuple


class TestRoundUpTuple(unittest.TestCase):
    def test_empty_tuple(self):
        result = round_up_tuple(())
        self.assertEqual(result, {})

    def test_single_number(self):
        result = round_up_tuple((1.2345,))
        self.assertEqual(result, {0: 1.23})

    def test_multiple_numbers(self):
        result = round_up_tuple((1.2345, 2.3456, 3.4567))
        self.assertEqual(result, {0: 1.23, 1: 2.35, 2: 3.46})

    def test_negative_numbers(self):
        result = round_up_tuple((-1.2345, -2.3456, -3.4567))
        self.assertEqual(result, {0: -1.23, 1: -2.35, 2: -3.46})

    def test_zero_numbers(self):
        result = round_up_tuple((0.0, 0.0, 0.0))
        self.assertEqual(result, {0: 0.0, 1: 0.0, 2: 0.0})

    def test_mixed_numbers(self):
        result = round_up_tuple((1.2345, -2.3456, 0.0))
        self.assertEqual(result, {0: 1.23, 1: -2.35, 2: 0.0})


if __name__ == "__main__":
    unittest.main()
