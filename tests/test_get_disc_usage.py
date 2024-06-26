import unittest
from unittest.mock import patch, MagicMock

from app.core.adapters.psutil_adapter import PsutilAdapter


class TestPsutilAdapter(unittest.TestCase):
    def setUp(self):
        self.psutil_adapter = PsutilAdapter()

    @patch('app.core.adapters.psutil_adapter.psutil.disk_partitions')
    @patch('app.core.adapters.psutil_adapter.psutil.disk_usage')
    def test_get_disk_usage(self, mock_disk_usage, mock_disk_partitions):
        # Mock the disk partitions
        mock_disk_partitions.return_value = [
            MagicMock(device='/dev/sda1', fstype='ext4', mountpoint='/'),
            MagicMock(device='/dev/sdb1', fstype='ext4', mountpoint='/home'),
        ]

        # Mock the disk usage
        mock_disk_usage.side_effect = [
            MagicMock(total=100, used=50, free=50, percent=50.0),
            MagicMock(total=200, used=100, free=100, percent=50.0),
        ]

        # Call the function
        result = self.psutil_adapter.get_disk_usage()

        # Check the result
        expected_result = [
            {
                'device_name': '/dev/sda1',
                'fs_type': 'ext4',
                'mnt_point': '/',
                'size': '50 B',
                'used': '25 B',
                'free': '25 B',
                'percent': 50.0,
            },
            {
                'device_name': '/dev/sdb1',
                'fs_type': 'ext4',
                'mnt_point': '/home',
                'size': '100 B',
                'used': '50 B',
                'free': '50 B',
                'percent': 50.0,
            },
        ]
        self.assertEqual(result, expected_result)

    @patch('app.core.adapters.psutil_adapter.psutil.disk_partitions')
    @patch('app.core.adapters.psutil_adapter.psutil.disk_usage')
    def test_get_disk_usage_permission_error(self, mock_disk_usage, mock_disk_partitions):
        # Mock the disk partitions
        mock_disk_partitions.side_effect = PermissionError("Permission denied")

        # Call the function and check for the exception
        with self.assertRaises(PermissionError):
            self.psutil_adapter.get_disk_usage()

    @patch('app.core.adapters.psutil_adapter.psutil.disk_partitions')
    @patch('app.core.adapters.psutil_adapter.psutil.disk_usage')
    def test_get_disk_usage_key_error(self, mock_disk_usage, mock_disk_partitions):
        # Mock the disk partitions
        mock_disk_partitions.return_value = [
            MagicMock(device='/dev/sda1', fstype='ext4', mountpoint='/'),
            MagicMock(device='/dev/sdb1', fstype='ext4', mountpoint='/home'),
        ]

        # Mock the disk usage
        mock_disk_usage.side_effect = [
            MagicMock(total=100, used=50, free=50, percent=50.0),
            KeyError("Error retrieving disk usage"),
        ]

        # Call the function and check for the exception
        with self.assertRaises(KeyError):
            self.psutil_adapter.get_disk_usage()


if __name__ == '__main__':
    unittest.main()
