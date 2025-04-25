import unittest

from pytmbot.utils.utilities import find_in_args


class TestFindInArgs(unittest.TestCase):

    def test_find_in_args_with_integers(self):
        # Test finding the first occurrence of an integer in a tuple of mixed types
        result = find_in_args((1, "a", 2.5), int)
        self.assertEqual(result, 1)

    def test_find_in_args_with_strings(self):
        # Test finding the first occurrence of a string in a tuple of strings
        result = find_in_args(("apple", "banana", "cherry"), str)
        self.assertEqual(result, "apple")

    def test_find_in_args_with_empty_tuple(self):
        # Test handling an empty tuple input
        result = find_in_args((), int)
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
