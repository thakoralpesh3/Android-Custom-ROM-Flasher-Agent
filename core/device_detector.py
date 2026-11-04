"""
Device Detection and Inspection Module for Android Custom ROM Flasher Agent.
Identifies connected devices in ADB, Fastboot, FastbootD, and Recovery modes.
"""

from typing import List, Dict, Any, Optional, Tuple
from .adb_manager import ADBManager


class DeviceDetector:
    """Discovers and queries Android devices across different connection states."""

    def __init__(self, adb_manager: ADBManager):
        self.adb = adb_manager

    def scan_devices(self) -> List[Dict[str, Any]]:
        """
        Scan all connected devices via ADB and Fastboot.
        Returns a normalized list of device status dictionaries.
        """
        devices: List[Dict[str, Any]] = []
        if not self.adb.is_ready():
            return devices

        # 1. Scan ADB devices
        code, out, _ = self.adb.run_adb(["devices", "-l"], timeout=5)
        if code == 0 and out:
            lines = out.splitlines()[1:]  # Skip "List of devices attached"
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                parts = line.split()
                if len(parts) >= 2:
                    serial = parts[0]
                    state = parts[1]
                    details = self._get_adb_device_details(serial, state)
                    devices.append(details)

        # 2. Scan Fastboot devices
        code_fb, out_fb, _ = self.adb.run_fastboot(["devices"], timeout=5)
        if code_fb == 0 and out_fb:
            lines_fb = out_fb.splitlines()
            for line in lines_fb:
                line = line.strip()
                if not line:
                    continue
                parts = line.split()
                if len(parts) >= 2:
                    serial = parts[0]
                    state_raw = parts[1]  # "fastboot"
                    details_fb = self._get_fastboot_device_details(serial)
                    devices.append(details_fb)

        return devices

    def _get_adb_device_details(self, serial: str, state: str) -> Dict[str, Any]:
        """Fetch details for an ADB connected device."""
        info = {
            "serial": serial,
            "mode": state,  # device, recovery, sideload, unauthorized
            "interface": "adb",
            "model": "Unknown",
            "brand": "Unknown",
            "codename": "Unknown",
            "android_version": "Unknown",
            "battery_level": None,
            "unlocked": None,
            "status_message": "Connected"
        }

        if state == "unauthorized":
            info["status_message"] = "Unauthorized. Please tap 'Allow USB Debugging' on phone screen."
            return info

        if state == "recovery":
            info["status_message"] = "Device is in Recovery Mode."
            # In recovery, getprop might still be accessible
            _, codename, _ = self.adb.run_adb(["shell", "getprop", "ro.product.device"], serial=serial, timeout=3)
            if codename:
                info["codename"] = codename.strip()
            return info

        if state == "sideload":
            info["status_message"] = "Device is in Sideload Mode (Ready for ROM flash)."
            return info

        if state == "device":
            # Query properties
            _, codename, _ = self.adb.run_adb(["shell", "getprop", "ro.product.device"], serial=serial, timeout=3)
            _, model, _ = self.adb.run_adb(["shell", "getprop", "ro.product.model"], serial=serial, timeout=3)
            _, brand, _ = self.adb.run_adb(["shell", "getprop", "ro.product.brand"], serial=serial, timeout=3)
            _, version, _ = self.adb.run_adb(["shell", "getprop", "ro.build.version.release"], serial=serial, timeout=3)
            _, locked, _ = self.adb.run_adb(["shell", "getprop", "ro.boot.flash.locked"], serial=serial, timeout=3)

            # Battery level check
            _, battery_out, _ = self.adb.run_adb(["shell", "dumpsys", "battery"], serial=serial, timeout=4)
            battery_pct = None
            if battery_out:
                for b_line in battery_out.splitlines():
                    if "level:" in b_line:
                        try:
                            battery_pct = int(b_line.split(":")[-1].strip())
                        except ValueError:
                            pass

            info["model"] = model.strip() if model else "Android Device"
            info["brand"] = brand.strip().capitalize() if brand else "Android"
            info["codename"] = codename.strip() if codename else "unknown"
            info["android_version"] = version.strip() if version else "N/A"
            info["battery_level"] = battery_pct
            info["unlocked"] = (locked.strip() == "0") if locked else None
            info["status_message"] = f"Online (Android {info['android_version']})"

        return info

    def _get_fastboot_device_details(self, serial: str) -> Dict[str, Any]:
        """Fetch details for a Fastboot or FastbootD connected device."""
        info = {
            "serial": serial,
            "mode": "fastboot",
            "interface": "fastboot",
            "model": "Fastboot Device",
            "brand": "Android",
            "codename": "Unknown",
            "android_version": "N/A",
            "battery_level": None,
            "unlocked": None,
            "is_userspace": False,
            "current_slot": None,
            "status_message": "Fastboot Bootloader Mode"
        }

        # Check product / codename
        _, out_product, err_product = self.adb.run_fastboot(["getvar", "product"], serial=serial, timeout=3)
        combined_product = f"{out_product} {err_product}"
        for line in combined_product.splitlines():
            if "product:" in line:
                val = line.split("product:")[-1].strip()
                if val:
                    info["codename"] = val
                    info["model"] = val.capitalize()

        # Check userspace (fastbootd)
        _, out_user, err_user = self.adb.run_fastboot(["getvar", "is-userspace"], serial=serial, timeout=3)
        combined_user = f"{out_user} {err_user}"
        if "yes" in combined_user.lower():
            info["is_userspace"] = True
            info["mode"] = "fastbootd"
            info["status_message"] = "FastbootD Mode (Dynamic Partitions Ready)"

        # Check unlocked state
        _, out_unlock, err_unlock = self.adb.run_fastboot(["getvar", "unlocked"], serial=serial, timeout=3)
        combined_unlock = f"{out_unlock} {err_unlock}"
        if "unlocked: yes" in combined_unlock.lower():
            info["unlocked"] = True
        elif "unlocked: no" in combined_unlock.lower():
            info["unlocked"] = False

        # Check current slot
        _, out_slot, err_slot = self.adb.run_fastboot(["getvar", "current-slot"], serial=serial, timeout=3)
        combined_slot = f"{out_slot} {err_slot}"
        for line in combined_slot.splitlines():
            if "current-slot:" in line:
                info["current_slot"] = line.split("current-slot:")[-1].strip()

        # Check battery voltage / level
        _, out_bat, err_bat = self.adb.run_fastboot(["getvar", "battery-soc-ok"], serial=serial, timeout=3)
        if "yes" in f"{out_bat} {err_bat}".lower():
            info["battery_level"] = 100  # fastboot reports OK

        return info

    def reboot_device(self, target: str, serial: Optional[str] = None) -> Tuple[bool, str]:
        """
        Reboot device into desired mode:
        targets: 'system', 'recovery', 'bootloader', 'fastbootd', 'sideload'
        """
        # First check current mode of device
        devices = self.scan_devices()
        dev = next((d for d in devices if d["serial"] == serial), None) if serial else (devices[0] if devices else None)

        if not dev:
            return False, "No device detected to reboot."

        current_interface = dev.get("interface", "adb")
        dev_serial = dev["serial"]

        if current_interface == "adb":
            if target == "system":
                code, _, err = self.adb.run_adb(["reboot"], serial=dev_serial)
            elif target == "recovery":
                code, _, err = self.adb.run_adb(["reboot", "recovery"], serial=dev_serial)
            elif target in ["bootloader", "fastboot"]:
                code, _, err = self.adb.run_adb(["reboot", "bootloader"], serial=dev_serial)
            elif target == "fastbootd":
                code, _, err = self.adb.run_adb(["reboot", "fastboot"], serial=dev_serial)
            elif target == "sideload":
                code, _, err = self.adb.run_adb(["reboot", "sideload"], serial=dev_serial)
            else:
                return False, f"Unknown reboot target: {target}"

            if code == 0:
                return True, f"Rebooting device {dev_serial} to {target}..."
            return False, f"Reboot command failed: {err}"

        elif current_interface == "fastboot":
            if target == "system":
                code, _, err = self.adb.run_fastboot(["reboot"], serial=dev_serial)
            elif target == "recovery":
                code, _, err = self.adb.run_fastboot(["reboot", "recovery"], serial=dev_serial)
            elif target in ["bootloader", "fastboot"]:
                code, _, err = self.adb.run_fastboot(["reboot", "bootloader"], serial=dev_serial)
            elif target == "fastbootd":
                code, _, err = self.adb.run_fastboot(["reboot", "fastboot"], serial=dev_serial)
            else:
                return False, f"Reboot target {target} not supported directly from fastboot."

            if code == 0:
                return True, f"Rebooting fastboot device {dev_serial} to {target}..."
            return False, f"Fastboot reboot command failed: {err}"

        return False, "Unknown device interface."
