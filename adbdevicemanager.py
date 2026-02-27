import os
import shlex
import shutil
import subprocess
import sys
import time

from PIL import Image as PILImage
from ppadb.client import Client as AdbClient


class AdbDeviceManager:
    def __init__(self, device_name: str | None = None, exit_on_error: bool = True) -> None:
        """
        Initialize the ADB Device Manager

        Args:
            device_name: Optional name/serial of the device to manage.
                         If None, attempts to auto-select if only one device is available.
            exit_on_error: Whether to exit the program if device initialization fails
        """
        if not self.check_adb_installed():
            error_msg = "adb is not installed or not in PATH. Please install adb and ensure it is in your PATH."
            if exit_on_error:
                print(error_msg, file=sys.stderr)
                sys.exit(1)
            else:
                raise RuntimeError(error_msg)

        available_devices = self.get_available_devices()
        if not available_devices:
            error_msg = "No devices connected. Please connect a device and try again."
            if exit_on_error:
                print(error_msg, file=sys.stderr)
                sys.exit(1)
            else:
                raise RuntimeError(error_msg)

        selected_device_name: str | None = None

        if device_name:
            if device_name not in available_devices:
                error_msg = f"Device {device_name} not found. Available devices: {available_devices}"
                if exit_on_error:
                    print(error_msg, file=sys.stderr)
                    sys.exit(1)
                else:
                    raise RuntimeError(error_msg)
            selected_device_name = device_name
        else:  # No device_name provided, try auto-selection
            if len(available_devices) == 1:
                selected_device_name = available_devices[0]
                print(
                    f"No device specified, automatically selected: {selected_device_name}")
            elif len(available_devices) > 1:
                error_msg = f"Multiple devices connected: {available_devices}. Please specify a device in config.yaml or connect only one device."
                if exit_on_error:
                    print(error_msg, file=sys.stderr)
                    sys.exit(1)
                else:
                    raise RuntimeError(error_msg)
            # If len(available_devices) == 0, it's already caught by the earlier check

        # At this point, selected_device_name should always be set due to the logic above
        # Initialize the device
        self.device = AdbClient().device(selected_device_name)
        self.device_serial = selected_device_name
        self.flutter_process: subprocess.Popen | None = None
        self.flutter_log_path: str | None = None
        self._flutter_log_handle = None

    @staticmethod
    def check_adb_installed() -> bool:
        """Check if ADB is installed on the system."""
        try:
            subprocess.run(["adb", "version"], check=True,
                           stdout=subprocess.PIPE)
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False

    @staticmethod
    def get_available_devices() -> list[str]:
        """Get a list of available devices."""
        return [device.serial for device in AdbClient().devices()]

    def get_packages(self) -> str:
        command = "pm list packages"
        packages = self.device.shell(command).strip().split("\n")
        result = [package[8:] for package in packages]
        output = "\n".join(result)
        return output

    def get_package_action_intents(self, package_name: str) -> list[str]:
        command = f"dumpsys package {package_name}"
        output = self.device.shell(command)

        resolver_table_start = output.find("Activity Resolver Table:")
        if resolver_table_start == -1:
            return []
        resolver_section = output[resolver_table_start:]

        non_data_start = resolver_section.find("\n  Non-Data Actions:")
        if non_data_start == -1:
            return []

        section_end = resolver_section[non_data_start:].find("\n\n")
        if section_end == -1:
            non_data_section = resolver_section[non_data_start:]
        else:
            non_data_section = resolver_section[
                non_data_start: non_data_start + section_end
            ]

        actions = []
        for line in non_data_section.split("\n"):
            line = line.strip()
            if line.startswith("android.") or line.startswith("com."):
                actions.append(line)

        return actions

    def execute_adb_shell_command(self, command: str) -> str:
        """Executes an ADB command and returns the output."""
        if command.startswith("adb shell "):
            command = command[10:]
        elif command.startswith("adb "):
            command = command[4:]
        result = self.device.shell(command)
        return result

    def launch_app(self, package_name: str, activity_name: str | None = None, stop_first: bool = False) -> str:
        """Launches an Android app by package name and optional activity."""
        output_parts = []
        if stop_first:
            self.device.shell(f"am force-stop {package_name}")
            output_parts.append(f"Force-stopped {package_name}")

        if activity_name:
            component = activity_name if "/" in activity_name else f"{package_name}/{activity_name}"
            launch_output = self.device.shell(f"am start -n {component}")
        else:
            launch_output = self.device.shell(
                f"monkey -p {package_name} -c android.intent.category.LAUNCHER 1"
            )

        launch_output = launch_output.strip()
        if launch_output:
            output_parts.append(launch_output)

        if not output_parts:
            return f"Launch command sent for {package_name}"

        return "\n".join(output_parts)

    @staticmethod
    def _tail_file(file_path: str, lines: int = 60) -> str:
        if not os.path.exists(file_path):
            return f"No log file found at {file_path}"
        with open(file_path, encoding="utf-8", errors="replace") as handle:
            file_lines = handle.readlines()
        if not file_lines:
            return "(log file is empty)"
        return "".join(file_lines[-lines:]).rstrip()

    def _resolve_flutter_executable(self, flutter_executable: str) -> str:
        # If an explicit file path is provided, use it directly.
        if os.path.sep in flutter_executable or (
            os.path.altsep and os.path.altsep in flutter_executable
        ):
            if not os.path.exists(flutter_executable):
                raise RuntimeError(
                    f"Flutter executable not found at {flutter_executable}"
                )
            return flutter_executable

        resolved = shutil.which(flutter_executable)
        if resolved:
            return resolved

        raise RuntimeError(
            f"Could not find '{flutter_executable}' on PATH. "
            "Pass an absolute flutter executable path."
        )

    def _cleanup_flutter_process_state(self) -> None:
        if self._flutter_log_handle and not self._flutter_log_handle.closed:
            self._flutter_log_handle.close()
        self._flutter_log_handle = None
        self.flutter_process = None

    def start_flutter_run(
        self,
        project_dir: str,
        target: str = "lib/main.dart",
        flutter_executable: str = "flutter",
        additional_args: str | None = None,
        startup_wait_seconds: int = 8,
    ) -> str:
        """
        Start `flutter run` in a managed subprocess tied to the selected device.
        """
        if self.flutter_process and self.flutter_process.poll() is None:
            return (
                f"Flutter run already active (pid: {self.flutter_process.pid}). "
                "Use hot_reload_flutter_run / hot_restart_flutter_run or stop_flutter_run."
            )

        if self.flutter_process and self.flutter_process.poll() is not None:
            self._cleanup_flutter_process_state()

        if not os.path.isdir(project_dir):
            raise RuntimeError(f"Project directory not found: {project_dir}")

        flutter_cmd = self._resolve_flutter_executable(flutter_executable)

        command = [flutter_cmd, "run", "-d", self.device_serial, "-t", target]
        if additional_args:
            command.extend(shlex.split(additional_args, posix=os.name != "nt"))

        self.flutter_log_path = os.path.join(project_dir, ".mcp_flutter_run.log")
        self._flutter_log_handle = open(self.flutter_log_path, "w", encoding="utf-8")

        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        self.flutter_process = subprocess.Popen(
            command,
            cwd=project_dir,
            stdin=subprocess.PIPE,
            stdout=self._flutter_log_handle,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            creationflags=creationflags,
        )

        time.sleep(max(0, startup_wait_seconds))

        if self.flutter_process.poll() is not None:
            exit_code = self.flutter_process.returncode
            failure_tail = self._tail_file(self.flutter_log_path, 80)
            self._cleanup_flutter_process_state()
            return (
                f"flutter run exited early with code {exit_code}.\n"
                f"Log tail:\n{failure_tail}"
            )

        return (
            f"Started flutter run (pid: {self.flutter_process.pid}) on device {self.device_serial}.\n"
            f"Log file: {self.flutter_log_path}"
        )

    def hot_reload_flutter_run(self) -> str:
        """Send hot reload command (`r`) to the managed flutter run process."""
        if not self.flutter_process or self.flutter_process.poll() is not None:
            return "No active flutter run process. Start one with start_flutter_run first."

        if not self.flutter_process.stdin:
            return "Flutter process stdin is unavailable; cannot send hot reload command."

        self.flutter_process.stdin.write("r\n")
        self.flutter_process.stdin.flush()
        return "Hot reload command sent to flutter run."

    def hot_restart_flutter_run(self) -> str:
        """Send hot restart command (`R`) to the managed flutter run process."""
        if not self.flutter_process or self.flutter_process.poll() is not None:
            return "No active flutter run process. Start one with start_flutter_run first."

        if not self.flutter_process.stdin:
            return "Flutter process stdin is unavailable; cannot send hot restart command."

        self.flutter_process.stdin.write("R\n")
        self.flutter_process.stdin.flush()
        return "Hot restart command sent to flutter run."

    def stop_flutter_run(self, graceful_wait_seconds: int = 10) -> str:
        """Stop the managed flutter run process, trying graceful quit first."""
        if not self.flutter_process or self.flutter_process.poll() is not None:
            self._cleanup_flutter_process_state()
            return "No active flutter run process."

        pid = self.flutter_process.pid
        if self.flutter_process.stdin:
            self.flutter_process.stdin.write("q\n")
            self.flutter_process.stdin.flush()

        try:
            self.flutter_process.wait(timeout=max(1, graceful_wait_seconds))
            stopped_gracefully = True
        except subprocess.TimeoutExpired:
            self.flutter_process.kill()
            self.flutter_process.wait(timeout=5)
            stopped_gracefully = False

        self._cleanup_flutter_process_state()
        if stopped_gracefully:
            return f"Stopped flutter run gracefully (pid: {pid})."
        return f"Force-killed flutter run process (pid: {pid})."

    def get_flutter_run_log(self, lines: int = 60) -> str:
        """Read the tail of the managed flutter run log file."""
        if not self.flutter_log_path:
            return "No flutter log available yet. Start flutter run first."

        if self._flutter_log_handle and not self._flutter_log_handle.closed:
            self._flutter_log_handle.flush()

        return self._tail_file(self.flutter_log_path, lines=max(1, lines))

    def take_screenshot(self) -> None:
        self.device.shell("screencap -p /sdcard/screenshot.png")
        self.device.pull("/sdcard/screenshot.png", "screenshot.png")
        self.device.shell("rm /sdcard/screenshot.png")

        # compressing the ss to avoid "maximum call stack exceeded" error on claude desktop
        with PILImage.open("screenshot.png") as img:
            width, height = img.size
            new_width = int(width * 0.3)
            new_height = int(height * 0.3)
            resized_img = img.resize(
                (new_width, new_height), PILImage.Resampling.LANCZOS
            )

            resized_img.save(
                "compressed_screenshot.png", "PNG", quality=85, optimize=True
            )

    def get_uilayout(self) -> str:
        self.device.shell("uiautomator dump")
        self.device.pull("/sdcard/window_dump.xml", "window_dump.xml")
        self.device.shell("rm /sdcard/window_dump.xml")

        import re
        import xml.etree.ElementTree as ET

        def calculate_center(bounds_str):
            matches = re.findall(r"\[(\d+),(\d+)\]", bounds_str)
            if len(matches) == 2:
                x1, y1 = map(int, matches[0])
                x2, y2 = map(int, matches[1])
                center_x = (x1 + x2) // 2
                center_y = (y1 + y2) // 2
                return center_x, center_y
            return None

        tree = ET.parse("window_dump.xml")
        root = tree.getroot()

        clickable_elements = []
        for element in root.findall(".//node[@clickable='true']"):
            text = element.get("text", "")
            content_desc = element.get("content-desc", "")
            bounds = element.get("bounds", "")

            # Only include elements that have either text or content description
            if text or content_desc:
                center = calculate_center(bounds)
                element_info = "Clickable element:"
                if text:
                    element_info += f"\n  Text: {text}"
                if content_desc:
                    element_info += f"\n  Description: {content_desc}"
                element_info += f"\n  Bounds: {bounds}"
                if center:
                    element_info += f"\n  Center: ({center[0]}, {center[1]})"
                clickable_elements.append(element_info)

        if not clickable_elements:
            return "No clickable elements found with text or description"
        else:
            result = "\n\n".join(clickable_elements)
            return result
