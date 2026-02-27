"""
Tests for AdbDeviceManager
"""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

from adbdevicemanager import AdbDeviceManager

# Add the parent directory to the path so we can import our modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestAdbDeviceManager:
    """Test AdbDeviceManager functionality"""

    @patch('adbdevicemanager.AdbDeviceManager.check_adb_installed')
    @patch('adbdevicemanager.AdbDeviceManager.get_available_devices')
    @patch('adbdevicemanager.AdbClient')
    def test_single_device_auto_selection(self, mock_adb_client, mock_get_devices, mock_check_adb):
        """Test auto-selection when only one device is connected"""
        # Setup mocks
        mock_check_adb.return_value = True
        mock_get_devices.return_value = ["device123"]
        mock_device = MagicMock()
        mock_adb_client.return_value.device.return_value = mock_device

        # Test with device_name=None (auto-selection)
        with patch('builtins.print') as mock_print:
            manager = AdbDeviceManager(device_name=None, exit_on_error=False)

            # Verify the correct device was selected
            mock_adb_client.return_value.device.assert_called_once_with(
                "device123")
            assert manager.device == mock_device

            # Verify auto-selection message was printed
            mock_print.assert_called_with(
                "No device specified, automatically selected: device123")

    @patch('adbdevicemanager.AdbDeviceManager.check_adb_installed')
    @patch('adbdevicemanager.AdbDeviceManager.get_available_devices')
    def test_multiple_devices_no_selection_error(self, mock_get_devices, mock_check_adb):
        """Test error when multiple devices are connected but none specified"""
        # Setup mocks
        mock_check_adb.return_value = True
        mock_get_devices.return_value = ["device123", "device456"]

        # Test with device_name=None and multiple devices
        with pytest.raises(RuntimeError) as exc_info:
            AdbDeviceManager(device_name=None, exit_on_error=False)

        assert "Multiple devices connected" in str(exc_info.value)
        assert "device123" in str(exc_info.value)
        assert "device456" in str(exc_info.value)

    @patch('adbdevicemanager.AdbDeviceManager.check_adb_installed')
    @patch('adbdevicemanager.AdbDeviceManager.get_available_devices')
    @patch('adbdevicemanager.AdbClient')
    def test_specific_device_selection(self, mock_adb_client, mock_get_devices, mock_check_adb):
        """Test selecting a specific device"""
        # Setup mocks
        mock_check_adb.return_value = True
        mock_get_devices.return_value = ["device123", "device456"]
        mock_device = MagicMock()
        mock_adb_client.return_value.device.return_value = mock_device

        # Test with specific device name
        manager = AdbDeviceManager(
            device_name="device456", exit_on_error=False)

        # Verify the correct device was selected
        mock_adb_client.return_value.device.assert_called_once_with(
            "device456")
        assert manager.device == mock_device

    @patch('adbdevicemanager.AdbDeviceManager.check_adb_installed')
    @patch('adbdevicemanager.AdbDeviceManager.get_available_devices')
    def test_device_not_found_error(self, mock_get_devices, mock_check_adb):
        """Test error when specified device is not found"""
        # Setup mocks
        mock_check_adb.return_value = True
        mock_get_devices.return_value = ["device123", "device456"]

        # Test with non-existent device
        with pytest.raises(RuntimeError) as exc_info:
            AdbDeviceManager(device_name="non-existent-device",
                             exit_on_error=False)

        assert "Device non-existent-device not found" in str(exc_info.value)
        assert "Available devices" in str(exc_info.value)

    @patch('adbdevicemanager.AdbDeviceManager.check_adb_installed')
    @patch('adbdevicemanager.AdbDeviceManager.get_available_devices')
    def test_no_devices_connected_error(self, mock_get_devices, mock_check_adb):
        """Test error when no devices are connected"""
        # Setup mocks
        mock_check_adb.return_value = True
        mock_get_devices.return_value = []

        # Test with no devices
        with pytest.raises(RuntimeError) as exc_info:
            AdbDeviceManager(device_name=None, exit_on_error=False)

        assert "No devices connected" in str(exc_info.value)

    @patch('adbdevicemanager.AdbDeviceManager.check_adb_installed')
    def test_adb_not_installed_error(self, mock_check_adb):
        """Test error when ADB is not installed"""
        # Setup mocks
        mock_check_adb.return_value = False

        # Test with ADB not installed
        with pytest.raises(RuntimeError) as exc_info:
            AdbDeviceManager(device_name=None, exit_on_error=False)

        assert "adb is not installed" in str(exc_info.value)

    @patch('subprocess.run')
    def test_check_adb_installed_success(self, mock_run):
        """Test successful ADB installation check"""
        mock_run.return_value = MagicMock()  # Successful run

        result = AdbDeviceManager.check_adb_installed()

        assert result is True
        mock_run.assert_called_once()

    @patch('subprocess.run')
    def test_check_adb_installed_failure(self, mock_run):
        """Test failed ADB installation check"""
        mock_run.side_effect = FileNotFoundError()  # ADB not found

        result = AdbDeviceManager.check_adb_installed()

        assert result is False

    @patch('adbdevicemanager.AdbClient')
    def test_get_available_devices(self, mock_adb_client):
        """Test getting available devices"""
        # Setup mock devices
        mock_device1 = MagicMock()
        mock_device1.serial = "device123"
        mock_device2 = MagicMock()
        mock_device2.serial = "device456"

        mock_adb_client.return_value.devices.return_value = [
            mock_device1, mock_device2]

        devices = AdbDeviceManager.get_available_devices()

        assert devices == ["device123", "device456"]

    @patch('adbdevicemanager.AdbDeviceManager.check_adb_installed')
    @patch('adbdevicemanager.AdbDeviceManager.get_available_devices')
    @patch('adbdevicemanager.AdbClient')
    def test_exit_on_error_true(self, mock_adb_client, mock_get_devices, mock_check_adb):
        """Test that exit_on_error=True calls sys.exit"""
        # Setup mocks to trigger error
        mock_check_adb.return_value = True
        mock_get_devices.return_value = []  # No devices

        # Test with exit_on_error=True (default)
        with patch('sys.exit') as mock_exit:
            with patch('builtins.print'):  # Suppress error output
                AdbDeviceManager(device_name=None, exit_on_error=True)

            mock_exit.assert_called_once_with(1)

    @patch('adbdevicemanager.AdbDeviceManager.check_adb_installed')
    @patch('adbdevicemanager.AdbDeviceManager.get_available_devices')
    @patch('adbdevicemanager.AdbClient')
    def test_launch_app_default_uses_monkey(self, mock_adb_client, mock_get_devices, mock_check_adb):
        """Test app launch using package default launcher."""
        mock_check_adb.return_value = True
        mock_get_devices.return_value = ["device123"]
        mock_device = MagicMock()
        mock_device.shell.return_value = "Events injected: 1"
        mock_adb_client.return_value.device.return_value = mock_device

        manager = AdbDeviceManager(device_name=None, exit_on_error=False)
        output = manager.launch_app("com.example.app")

        mock_device.shell.assert_called_with(
            "monkey -p com.example.app -c android.intent.category.LAUNCHER 1"
        )
        assert "Events injected: 1" in output

    @patch('adbdevicemanager.AdbDeviceManager.check_adb_installed')
    @patch('adbdevicemanager.AdbDeviceManager.get_available_devices')
    @patch('adbdevicemanager.AdbClient')
    def test_hot_reload_writes_command_to_stdin(self, mock_adb_client, mock_get_devices, mock_check_adb):
        """Test hot reload command is sent to running flutter process."""
        mock_check_adb.return_value = True
        mock_get_devices.return_value = ["device123"]
        mock_device = MagicMock()
        mock_adb_client.return_value.device.return_value = mock_device

        manager = AdbDeviceManager(device_name=None, exit_on_error=False)
        mock_process = MagicMock()
        mock_process.poll.return_value = None
        mock_process.stdin = MagicMock()
        manager.flutter_process = mock_process

        result = manager.hot_reload_flutter_run()

        mock_process.stdin.write.assert_called_once_with("r\n")
        mock_process.stdin.flush.assert_called_once()
        assert "Hot reload command sent" in result

    @patch('adbdevicemanager.time.sleep')
    @patch('adbdevicemanager.subprocess.Popen')
    @patch('adbdevicemanager.shutil.which')
    @patch('adbdevicemanager.AdbDeviceManager.check_adb_installed')
    @patch('adbdevicemanager.AdbDeviceManager.get_available_devices')
    @patch('adbdevicemanager.AdbClient')
    def test_start_flutter_run_starts_process(
        self,
        mock_adb_client,
        mock_get_devices,
        mock_check_adb,
        mock_which,
        mock_popen,
        mock_sleep,
        tmp_path,
    ):
        """Test starting managed flutter run process."""
        mock_check_adb.return_value = True
        mock_get_devices.return_value = ["device123"]
        mock_device = MagicMock()
        mock_adb_client.return_value.device.return_value = mock_device
        mock_which.return_value = "/usr/bin/flutter"

        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.pid = 999
        mock_popen.return_value = mock_proc

        manager = AdbDeviceManager(device_name=None, exit_on_error=False)
        result = manager.start_flutter_run(
            project_dir=str(tmp_path),
            target="lib/main.dart",
            additional_args="--dart-define=FOO=bar",
            startup_wait_seconds=0,
        )

        called_command = mock_popen.call_args.args[0]
        assert called_command[0] == "/usr/bin/flutter"
        assert called_command[1:4] == ["run", "-d", "device123"]
        assert "--dart-define=FOO=bar" in called_command
        assert "Started flutter run" in result
