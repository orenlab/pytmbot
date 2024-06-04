import unittest
from unittest.mock import patch, MagicMock

from app.core.adapters.psutil_adapter import PsutilAdapter


class TestPsutilAdapter(unittest.TestCase):
    """
    Test case for the `get_net_io_counters` method of the `PsutilAdapter` class.

    This test case verifies that the `get_net_io_counters` method returns the expected data when called.

    Parameters:
        - mock_psutil: A MagicMock object representing the `psutil` module.

    Returns:
        None

    Raises:
        AssertionError: If the result of `get_net_io_counters` does not match the expected data.
    """

    @patch('app.core.adapters.psutil_adapter.psutil')
    def test_get_net_io_counters_returns_expected_data(self, mock_psutil):
        mock_net_io_stat = MagicMock()
        mock_net_io_stat.bytes_recv = 1000
        mock_net_io_stat.packets_recv = 100
        mock_net_io_stat.packets_sent = 10
        mock_net_io_stat.errin = 5
        mock_net_io_stat.errout = 3
        mock_net_io_stat.dropin = 2
        mock_net_io_stat.dropout = 1
        mock_psutil.net_io_counters.return_value = mock_net_io_stat

        adapter = PsutilAdapter()
        result = adapter.get_net_io_counters()

        self.assertEqual(result, [
            {
                'bytes_sent': '417.4 KiB',
                'bytes_recv': '1.0 KiB',
                'packets_sent': 10,
                'packets_recv': 100,
                'err_in': 5,
                'err_out': 3,
                'drop_in': 2,
                'drop_out': 1
            }
        ])

    @patch('app.core.adapters.psutil_adapter.psutil')
    def test_get_net_io_counters_handles_attribute_error(self, mock_psutil):
        mock_psutil.net_io_counters.side_effect = AttributeError('Test error')

        adapter = PsutilAdapter()
        result = adapter.get_net_io_counters()

        self.assertEqual(result, [])


if __name__ == '__main__':
    unittest.main()
