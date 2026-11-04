"""
Automated Custom ROM Flashing Engine.
Orchestrates the entire flashing lifecycle: device validation, bootloader unlock guidance,
custom recovery deployment, data wipe, zip sideloading / fastboot flashing, and reboot.
"""

import time
import subprocess
import threading
from pathlib import Path
from typing import Dict, List, Any, Optional, Callable
from .adb_manager import ADBManager
from .device_detector import DeviceDetector

BASE_DIR = Path(__file__).resolve().parent.parent
LOGS_DIR = BASE_DIR / "logs"


class FlashEngine:
    """Manages the full automated flashing pipeline with real-time log streaming."""

    def __init__(self, adb_manager: ADBManager, device_detector: DeviceDetector):
        self.adb = adb_manager
        self.detector = device_detector
        self.is_flashing = False
        self.current_step = ""
        self.progress_pct = 0
        self.log_history: List[str] = []
        self._cancel_requested = False
        LOGS_DIR.mkdir(parents=True, exist_ok=True)

    def log(self, message: str, level: str = "INFO"):
        """Append log message with timestamp and level."""
        timestamp = time.strftime("%H:%M:%S")
        entry = f"[{timestamp}] [{level}] {message}"
        self.log_history.append(entry)
        print(entry)

    def clear_logs(self):
        """Reset logs for a new flashing run."""
        self.log_history = []
        self.current_step = ""
        self.progress_pct = 0

    def start_flash_pipeline_async(
        self,
        serial: str,
        rom_path: str,
        recovery_path: Optional[str] = None,
        wipe_data: bool = True,
        addons: Optional[List[str]] = None,
        on_complete: Optional[Callable[[bool, str], None]] = None
    ):
        """Run the complete flashing pipeline in a background thread."""
        thread = threading.Thread(
            target=self._run_pipeline,
            args=(serial, rom_path, recovery_path, wipe_data, addons or [], on_complete),
            daemon=True
        )
        thread.start()

    def _wait_for_device(self, serial: str, expected_mode: str, timeout: int = 90) -> bool:
        """Wait for device to enter expected mode (e.g. recovery, fastboot, sideload)."""
        self.log(f"Waiting up to {timeout}s for device {serial} to enter {expected_mode} mode...", "INFO")
        start = time.time()
        while time.time() - start < timeout:
            if self._cancel_requested:
                return False
            devices = self.detector.scan_devices()
            for d in devices:
                # Match serial or accept if only 1 device is connected
                if d["serial"] == serial or len(devices) == 1:
                    if d["mode"] == expected_mode or (expected_mode == "fastboot" and d["interface"] == "fastboot"):
                        self.log(f"Device detected in {expected_mode} mode! ({d['serial']})", "SUCCESS")
                        return True
            time.sleep(2)
        return False

    def _run_pipeline(
        self,
        serial: str,
        rom_path: str,
        recovery_path: Optional[str],
        wipe_data: bool,
        addons: List[str],
        on_complete: Optional[Callable[[bool, str], None]]
    ):
        self.is_flashing = True
        self._cancel_requested = False
        self.clear_logs()

        rom_file = Path(rom_path)
        if not rom_file.exists():
            self.log(f"ROM file does not exist: {rom_path}", "ERROR")
            self.is_flashing = False
            if on_complete:
                on_complete(False, "ROM file not found")
            return

        success = False
        message = ""

        try:
            # ---------------------------------------------------------
            # STEP 1: Pre-flight Verification
            # ---------------------------------------------------------
            self.current_step = "Pre-flight Verification"
            self.progress_pct = 5
            self.log("===================================================", "INFO")
            self.log(f"Starting Custom ROM Flashing Engine for {rom_file.name}", "INFO")
            self.log("===================================================", "INFO")

            devices = self.detector.scan_devices()
            target_device = next((d for d in devices if d["serial"] == serial), None)
            if not target_device and devices:
                target_device = devices[0]
                serial = target_device["serial"]

            if not target_device:
                raise RuntimeError("No target device found. Ensure USB connection and drivers are ready.")

            self.log(f"Target Device: {target_device.get('model')} ({serial}) in {target_device.get('mode')} mode", "INFO")

            # Check battery
            bat = target_device.get("battery_level")
            if bat is not None and bat < 25:
                self.log(f"Warning: Battery level is {bat}%. It is strongly recommended to charge to at least 40%.", "WARN")

            # ---------------------------------------------------------
            # STEP 2: Bootloader / Recovery Preparation
            # ---------------------------------------------------------
            self.current_step = "Preparing Recovery / Bootloader"
            self.progress_pct = 20

            # If a custom recovery image (TWRP / OrangeFox) is provided
            if recovery_path and Path(recovery_path).exists():
                rec_file = Path(recovery_path)
                self.log(f"Custom recovery supplied: {rec_file.name}. Flashing to bootloader...", "INFO")

                # If device in ADB mode, reboot to bootloader
                if target_device["interface"] == "adb":
                    self.log("Rebooting device to bootloader...", "INFO")
                    self.detector.reboot_device("bootloader", serial)
                    if not self._wait_for_device(serial, "fastboot"):
                        raise RuntimeError("Device failed to reboot into fastboot mode.")

                # Flash recovery image
                self.log(f"Flashing recovery partition with {rec_file.name}...", "INFO")
                code, out, err = self.adb.run_fastboot(["flash", "recovery", str(rec_file)], serial=serial)
                if code != 0:
                    # Some modern devices use boot partition instead of recovery
                    self.log("Standard recovery flash failed, attempting boot partition flash (A/B device)...", "WARN")
                    code, out, err = self.adb.run_fastboot(["flash", "boot", str(rec_file)], serial=serial)
                    if code != 0:
                        raise RuntimeError(f"Recovery flash failed: {err}")

                self.log("Recovery image successfully flashed to device.", "SUCCESS")

                # Reboot directly to recovery
                self.log("Rebooting into recovery...", "INFO")
                self.detector.reboot_device("recovery", serial)
                time.sleep(5)

            # ---------------------------------------------------------
            # STEP 3: Wipe / Factory Reset (if requested)
            # ---------------------------------------------------------
            self.current_step = "Wiping Data"
            self.progress_pct = 40

            if wipe_data:
                self.log("Executing clean wipe (UserData & Cache)...", "INFO")
                # If currently in fastboot
                current_devices = self.detector.scan_devices()
                dev = next((d for d in current_devices if d["serial"] == serial), current_devices[0] if current_devices else None)
                if dev and dev.get("interface") == "fastboot":
                    self.log("Formatting userdata via fastboot...", "INFO")
                    self.adb.run_fastboot(["erase", "userdata"], serial=serial)
                    self.adb.run_fastboot(["erase", "cache"], serial=serial)
                elif dev and dev.get("mode") == "recovery":
                    self.log("Device is in recovery mode. Formatting data recommended from recovery menu.", "INFO")

            # ---------------------------------------------------------
            # STEP 4: ROM Flashing
            # ---------------------------------------------------------
            self.current_step = "Flashing Custom ROM"
            self.progress_pct = 50

            if rom_file.suffix.lower() == ".zip":
                # Method A: Sideload via Recovery
                self.log("Detected flashable ROM zip package. Sideload procedure initiating...", "INFO")

                # Ensure device is in sideload or recovery
                curr_devs = self.detector.scan_devices()
                cur_dev = next((d for d in curr_devs if d["serial"] == serial), curr_devs[0] if curr_devs else None)

                if cur_dev and cur_dev.get("interface") == "fastboot":
                    self.log("Rebooting from fastboot to recovery for sideloading...", "INFO")
                    self.detector.reboot_device("recovery", serial)
                    self._wait_for_device(serial, "recovery", timeout=60)

                # Prompt user or verify sideload mode
                self.log(f"Starting ADB Sideload for {rom_file.name} (File size: {round(rom_file.stat().st_size / (1024*1024), 1)} MB)...", "INFO")
                self.log("Please ensure phone recovery shows 'Apply update from ADB' / 'Sideload' if required.", "INFO")

                # Execute adb sideload with progress monitoring
                adb_cmd = [self.adb.adb_bin]
                if serial:
                    adb_cmd.extend(["-s", serial])
                adb_cmd.extend(["sideload", str(rom_file)])

                process = subprocess.Popen(
                    adb_cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1
                )

                while True:
                    line = process.stdout.readline()
                    if not line and process.poll() is not None:
                        break
                    line = line.strip()
                    if line:
                        self.log(f"[ADB] {line}", "INFO")
                        # Parse sideload percentage e.g. "serving: 'rom.zip'  (~47%)"
                        if "%" in line:
                            try:
                                pct_str = line.split("%")[0].split("(")[-1].replace("~", "").strip()
                                self.progress_pct = 50 + int(int(pct_str) * 0.35)
                            except Exception:
                                pass

                return_code = process.poll()
                if return_code != 0:
                    raise RuntimeError(f"ADB sideload failed with exit code {return_code}")

                self.log("ROM zip package sideload completed successfully!", "SUCCESS")

            elif rom_file.suffix.lower() == ".img":
                # Method B: Fastboot image flashing (GSI / System / Boot)
                self.log("Detected single partition image. Flashing via Fastboot...", "INFO")
                curr_devs = self.detector.scan_devices()
                cur_dev = next((d for d in curr_devs if d["serial"] == serial), curr_devs[0] if curr_devs else None)

                if cur_dev and cur_dev.get("interface") == "adb":
                    self.log("Rebooting to fastbootd for partition flashing...", "INFO")
                    self.detector.reboot_device("fastbootd", serial)
                    self._wait_for_device(serial, "fastboot")

                partition = "system"
                if "boot" in rom_file.name.lower():
                    partition = "boot"
                elif "vendor" in rom_file.name.lower():
                    partition = "vendor"

                self.log(f"Flashing partition '{partition}' with {rom_file.name}...", "INFO")
                code, out, err = self.adb.run_fastboot(["flash", partition, str(rom_file)], serial=serial)
                if code != 0:
                    raise RuntimeError(f"Fastboot flash failed: {err}")

                self.log(f"Partition '{partition}' successfully flashed!", "SUCCESS")

            # ---------------------------------------------------------
            # STEP 5: Add-ons (GApps / Magisk Root)
            # ---------------------------------------------------------
            if addons:
                self.current_step = "Flashing Addons"
                self.progress_pct = 88
                for addon_path in addons:
                    addon_file = Path(addon_path)
                    if addon_file.exists():
                        self.log(f"Sideloading addon: {addon_file.name}...", "INFO")
                        code, out, err = self.adb.run_adb(["sideload", str(addon_file)], serial=serial, timeout=300)
                        if code == 0:
                            self.log(f"Addon {addon_file.name} installed successfully.", "SUCCESS")
                        else:
                            self.log(f"Addon {addon_file.name} failed: {err}", "WARN")

            # ---------------------------------------------------------
            # STEP 6: Reboot System
            # ---------------------------------------------------------
            self.current_step = "Rebooting System"
            self.progress_pct = 98
            self.log("Flashing operations completed. Rebooting phone into newly installed Custom ROM...", "INFO")
            self.detector.reboot_device("system", serial)

            self.progress_pct = 100
            self.current_step = "Completed"
            self.log("===================================================", "SUCCESS")
            self.log("CONGRATULATIONS! Custom ROM installation complete.", "SUCCESS")
            self.log("First boot typically takes 3 to 7 minutes. Please wait.", "SUCCESS")
            self.log("===================================================", "SUCCESS")

            success = True
            message = "Custom ROM installed successfully!"

        except Exception as e:
            self.current_step = "Failed"
            self.log(f"Flashing process halted: {str(e)}", "ERROR")
            success = False
            message = str(e)

        finally:
            self.is_flashing = False
            # Save log session
            session_log = LOGS_DIR / f"flash_session_{int(time.time())}.log"
            try:
                with open(session_log, "w", encoding="utf-8") as f_log:
                    f_log.write("\n".join(self.log_history))
            except Exception:
                pass

            if on_complete:
                on_complete(success, message)
