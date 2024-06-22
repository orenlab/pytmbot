import unittest
from unittest.mock import patch

from app.core.adapters.psutil_adapter import PsutilAdapter


class TestPsutilAdapter(unittest.TestCase):
    @patch('app.core.adapters.psutil_adapter.psutil.getloadavg')
    def test_get_load_average(self, mock_getloadavg):
        # Test case: Load average is returned correctly
        mock_getloadavg.return_value = (0.1, 0.2, 0.3)
        load_average = PsutilAdapter.get_load_average()
        self.assertEqual(load_average, (0.1, 0.2, 0.3))

    @patch('app.core.adapters.psutil_adapter.psutil.getloadavg')
    def test_get_load_average_zero_values(self, mock_getloadavg):
        # Test case: Load average is returned correctly when all values are zero
        mock_getloadavg.return_value = (0.0, 0.0, 0.0)
        load_average = PsutilAdapter.get_load_average()
        self.assertEqual(load_average, (0.0, 0.0, 0.0))

    @patch('app.core.adapters.psutil_adapter.psutil.getloadavg')
    def test_get_load_average_negative_values(self, mock_getloadavg):
        # Test case: Load average is returned correctly when all values are negative
        mock_getloadavg.return_value = (-1.0, -2.0, -3.0)
        load_average = PsutilAdapter.get_load_average()
        self.assertEqual(load_average, (-1.0, -2.0, -3.0))


if __name__ == '__main__':
    unittest.main()
