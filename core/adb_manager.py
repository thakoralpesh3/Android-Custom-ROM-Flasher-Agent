"""
ADB and Fastboot Management Module for Android Custom ROM Flasher Agent.
Handles binary discovery, automatic downloading of Google platform-tools,
and safe command execution across ADB and Fastboot interfaces.
"""

import os
import shutil
import subprocess
import urllib.request
import zipfile
from pathlib import Path
from typing import Tuple, List, Dict, Optional

BASE_DIR = Path(__file__).resolve().parent.parent
TOOLS_DIR = BASE_DIR / "tools" / "platform-tools"
GOOGLE_PLATFORM_TOOLS_URL = "https://dl.google.com/android/repository/platform-tools-latest-linux.zip"


class ADBManager:
    """Manages adb and fastboot binaries, execution, and environment setup."""

    def __init__(self, tools_dir: Optional[Path] = None):
        self.tools_dir = tools_dir or TOOLS_DIR
        self.adb_bin = self._find_binary("adb")
        self.fastboot_bin = self._find_binary("fastboot")

    def _find_binary(self, name: str) -> Optional[str]:
        """Find binary in custom tools directory or system PATH."""
        # 1. Check local tools directory first
        local_path = self.tools_dir / name
        if local_path.is_file() and os.access(str(local_path), os.X_OK):
            return str(local_path)

        # 2. Check system PATH
        system_bin = shutil.which(name)
        if system_bin:
            return system_bin

        return None

    def is_ready(self) -> bool:
        """Returns True if both adb and fastboot binaries are available."""
        self.adb_bin = self._find_binary("adb")
        self.fastboot_bin = self._find_binary("fastboot")
        return bool(self.adb_bin and self.fastboot_bin)

    def download_platform_tools(self, progress_callback=None) -> Tuple[bool, str]:
        """
        Download and extract official Google Android platform-tools for Linux.
        """
        try:
            self.tools_dir.parent.mkdir(parents=True, exist_ok=True)
            zip_target = self.tools_dir.parent / "platform-tools.zip"

            if progress_callback:
                progress_callback("Downloading Google Android Platform Tools...")

            def _reporthook(block_num, block_size, total_size):
                if progress_callback and total_size > 0:
                    percent = min(100, int(block_num * block_size * 100 / total_size))
                    progress_callback(f"Downloading Platform Tools: {percent}%")

            urllib.request.urlretrieve(GOOGLE_PLATFORM_TOOLS_URL, str(zip_target), reporthook=_reporthook)

            if progress_callback:
                progress_callback("Extracting Platform Tools archive...")

            with zipfile.ZipFile(str(zip_target), "r") as zip_ref:
                zip_ref.extractall(str(self.tools_dir.parent))

            # Clean up zip
            if zip_target.exists():
                zip_target.unlink()

            # Ensure execution permissions for extracted binaries
            for bin_name in ["adb", "fastboot", "mke2fs"]:
                p = self.tools_dir / bin_name
                if p.exists():
                    p.chmod(p.stat().st_mode | 0o755)

            self.adb_bin = self._find_binary("adb")
            self.fastboot_bin = self._find_binary("fastboot")

            if self.is_ready():
                return True, "Platform tools successfully installed."
            return False, "Platform tools extracted but binaries not found or not executable."

        except Exception as e:
            return False, f"Failed to download platform-tools: {str(e)}"

    def run_adb(self, args: List[str], serial: Optional[str] = None, timeout: int = 120) -> Tuple[int, str, str]:
        """Execute an adb command safely."""
        if not self.adb_bin:
            return -1, "", "adb binary not found. Please install platform-tools."

        cmd = [self.adb_bin]
        if serial:
            cmd.extend(["-s", serial])
        cmd.extend(args)

        try:
            res = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=timeout
            )
            return res.returncode, res.stdout.strip(), res.stderr.strip()
        except subprocess.TimeoutExpired:
            return -1, "", f"Command timed out after {timeout} seconds: {' '.join(cmd)}"
        except Exception as e:
            return -1, "", str(e)

    def run_fastboot(self, args: List[str], serial: Optional[str] = None, timeout: int = 300) -> Tuple[int, str, str]:
        """Execute a fastboot command safely."""
        if not self.fastboot_bin:
            return -1, "", "fastboot binary not found. Please install platform-tools."

        cmd = [self.fastboot_bin]
        if serial:
            cmd.extend(["-s", serial])
        cmd.extend(args)

        try:
            res = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=timeout
            )
            return res.returncode, res.stdout.strip(), res.stderr.strip()
        except subprocess.TimeoutExpired:
            return -1, "", f"Command timed out after {timeout} seconds: {' '.join(cmd)}"
        except Exception as e:
            return -1, "", str(e)

    def get_version_info(self) -> Dict[str, str]:
        """Get version strings for adb and fastboot."""
        info = {
            "adb_path": self.adb_bin or "Missing",
            "fastboot_path": self.fastboot_bin or "Missing",
            "adb_version": "N/A",
            "fastboot_version": "N/A",
            "ready": self.is_ready()
        }

        if self.adb_bin:
            code, out, _ = self.run_adb(["version"], timeout=5)
            if code == 0 and out:
                info["adb_version"] = out.splitlines()[0]

        if self.fastboot_bin:
            code, out, _ = self.run_fastboot(["--version"], timeout=5)
            if code == 0 and out:
                info["fastboot_version"] = out.splitlines()[0]

        return info
