import unittest
from datetime import datetime
from unittest.mock import patch, MagicMock

from pytmbot.adapters.psutil.adapter import PsutilAdapter


class TestPsutilAdapter(unittest.TestCase):
    def setUp(self):
        """
        Create an instance of PsutilAdapter before each test.
        """
        self.adapter = PsutilAdapter()

    @patch("psutil.getloadavg")
    def test_get_load_average(self, mock_getloadavg):
        """
        Test the get_load_average method.
        """
        mock_getloadavg.return_value = (0.5, 0.7, 0.9)
        load_average = self.adapter.get_load_average()
        self.assertEqual(load_average, (0.5, 0.7, 0.9))
        mock_getloadavg.assert_called_once()

    @patch("psutil.virtual_memory")
    @patch("pytmbot.utils.utilities.set_naturalsize")
    def test_get_memory(self, mock_set_naturalsize, mock_virtual_memory):
        """
        Test the get_memory method.
        """
        mock_memory = MagicMock()
        mock_memory.total = 16384
        mock_memory.available = 8192
        mock_memory.percent = 50
        mock_memory.used = 8192
        mock_memory.free = 4096
        mock_memory.active = 2048
        mock_memory.inactive = 1024
        mock_memory.cached = 512
        mock_memory.shared = 256
        mock_virtual_memory.return_value = mock_memory
        mock_set_naturalsize.return_value = "16 MB"

        expected_memory = {
            "total": "16 MB",
            "available": "16 MB",
            "percent": 50,
            "used": "16 MB",
            "free": "4 MB",
            "active": "2 MB",
            "inactive": "1 MB",
            "cached": "512 B",
            "shared": "256 B",
        }

        memory = self.adapter.get_memory()
        self.assertEqual(memory, expected_memory)
        mock_virtual_memory.assert_called_once()
        mock_set_naturalsize.assert_called()

    @patch("psutil.disk_partitions")
    @patch("psutil.disk_usage")
    @patch("pytmbot.utils.utilities.set_naturalsize")
    def test_get_disk_usage(
        self, mock_set_naturalsize, mock_disk_usage, mock_disk_partitions
    ):
        """
        Test the get_disk_usage method.
        """
        mock_disk_partitions.return_value = [MagicMock(mountpoint="/")]
        mock_disk_usage.return_value = MagicMock(
            total=100000, used=50000, free=50000, percent=50
        )
        mock_set_naturalsize.return_value = "100 MB"

        expected_disk_usage = [
            {
                "device_name": "/",
                "fs_type": "",
                "mnt_point": "/",
                "size": "100 MB",
                "used": "50 MB",
                "free": "50 MB",
                "percent": 50,
            }
        ]

        disk_usage = self.adapter.get_disk_usage()
        self.assertEqual(disk_usage, expected_disk_usage)
        mock_disk_partitions.assert_called_once()
        mock_disk_usage.assert_called()
        mock_set_naturalsize.assert_called()

    @patch("psutil.swap_memory")
    @patch("pytmbot.utils.utilities.set_naturalsize")
    def test_get_swap_memory(self, mock_set_naturalsize, mock_swap_memory):
        """
        Test the get_swap_memory method.
        """
        mock_swap = MagicMock()
        mock_swap.total = 2048
        mock_swap.used = 1024
        mock_swap.free = 1024
        mock_swap.percent = 50
        mock_swap_memory.return_value = mock_swap
        mock_set_naturalsize.return_value = "2 MB"

        expected_swap = {"total": "2 MB", "used": "1 MB", "free": "1 MB", "percent": 50}

        swap_memory = self.adapter.get_swap_memory()
        self.assertEqual(swap_memory, expected_swap)
        mock_swap_memory.assert_called_once()
        mock_set_naturalsize.assert_called()

    @patch("psutil.sensors_temperatures")
    def test_get_sensors_temperatures(self, mock_sensors_temperatures):
        """
        Test the get_sensors_temperatures method.
        """
        mock_sensors_temperatures.return_value = {
            "coretemp": [MagicMock(label="Package id 0", current=70)],
            "nvme": [MagicMock(label="NVMe Sensor", current=30)],
        }

        expected_temps = [
            {"sensor_name": "coretemp", "sensor_value": 70},
            {"sensor_name": "nvme", "sensor_value": 30},
        ]

        sensors_temps = self.adapter.get_sensors_temperatures()
        self.assertEqual(sensors_temps, expected_temps)
        mock_sensors_temperatures.assert_called_once()

    @patch("psutil.boot_time")
    def test_get_uptime(self, mock_boot_time):
        """
        Test the get_uptime method.
        """
        mock_boot_time.return_value = datetime.now().timestamp() - 3600  # 1 hour ago
        expected_uptime = "1:00:00"
        uptime = self.adapter.get_uptime()
        self.assertEqual(uptime, expected_uptime)
        mock_boot_time.assert_called_once()

    @patch("psutil.process_iter")
    def test_get_process_counts(self, mock_process_iter):
        """
        Test the get_process_counts method.
        """
        mock_process = MagicMock()
        mock_process.status.side_effect = ["running", "sleeping", "idle", "running"]
        mock_process_iter.return_value = [
            mock_process,
            mock_process,
            mock_process,
            mock_process,
        ]

        expected_counts = {"running": 2, "sleeping": 1, "idle": 1, "total": 4}

        process_counts = self.adapter.get_process_counts()
        self.assertEqual(process_counts, expected_counts)
        mock_process_iter.assert_called_once()

    @patch("psutil.net_io_counters")
    @patch("pytmbot.utils.utilities.set_naturalsize")
    def test_get_net_io_counters(self, mock_set_naturalsize, mock_net_io_counters):
        """
        Test the get_net_io_counters method.
        """
        mock_net_io = MagicMock(
            bytes_sent=10000,
            bytes_recv=20000,
            packets_sent=50,
            packets_recv=60,
            errin=0,
            errout=1,
            dropin=0,
            dropout=0,
        )
        mock_net_io_counters.return_value = mock_net_io
        mock_set_naturalsize.return_value = "10 KB"

        expected_net_io = [
            {
                "bytes_sent": "10 KB",
                "bytes_recv": "20 KB",
                "packets_sent": 50,
                "packets_recv": 60,
                "err_in": 0,
                "err_out": 1,
                "drop_in": 0,
                "drop_out": 0,
            }
        ]

        net_io_counters = self.adapter.get_net_io_counters()
        self.assertEqual(net_io_counters, expected_net_io)
        mock_net_io_counters.assert_called_once()
        mock_set_naturalsize.assert_called()


if __name__ == "__main__":
    unittest.main()
