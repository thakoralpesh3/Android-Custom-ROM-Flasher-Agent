"""
Custom ROM and Recovery Package Management Module.
Supports local archive inspection, direct URL downloads with live progress,
and online device build catalog lookups.
"""

import os
import time
import zipfile
import hashlib
import threading
import urllib.request
from pathlib import Path
from typing import Dict, List, Any, Optional, Callable

BASE_DIR = Path(__file__).resolve().parent.parent
DOWNLOADS_DIR = BASE_DIR / "downloads"


class DownloadTask:
    """Represents a background file download task with progress tracking."""

    def __init__(self, url: str, target_path: Path, label: str = ""):
        self.url = url
        self.target_path = target_path
        self.label = label or target_path.name
        self.total_bytes = 0
        self.downloaded_bytes = 0
        self.percentage = 0.0
        self.speed_mbps = 0.0
        self.status = "queued"  # queued, downloading, completed, error, cancelled
        self.error_message = ""
        self._cancel_requested = False
        self._thread: Optional[threading.Thread] = None

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def cancel(self):
        self._cancel_requested = True
        self.status = "cancelled"

    def _run(self):
        self.status = "downloading"
        start_time = time.time()
        last_calc_time = start_time
        last_calc_bytes = 0

        try:
            req = urllib.request.Request(self.url, headers={"User-Agent": "Mozilla/5.0 DroidFlash/1.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                self.total_bytes = int(resp.headers.get("Content-Length", 0))
                self.target_path.parent.mkdir(parents=True, exist_ok=True)

                with open(self.target_path, "wb") as f_out:
                    chunk_size = 64 * 1024  # 64 KB
                    while not self._cancel_requested:
                        chunk = resp.read(chunk_size)
                        if not chunk:
                            break
                        f_out.write(chunk)
                        self.downloaded_bytes += len(chunk)

                        now = time.time()
                        if now - last_calc_time >= 0.5:
                            duration = now - last_calc_time
                            bytes_diff = self.downloaded_bytes - last_calc_bytes
                            self.speed_mbps = round((bytes_diff / (1024 * 1024)) / duration, 2)
                            if self.total_bytes > 0:
                                self.percentage = round((self.downloaded_bytes / self.total_bytes) * 100, 1)
                            last_calc_time = now
                            last_calc_bytes = self.downloaded_bytes

            if self._cancel_requested:
                self.status = "cancelled"
                if self.target_path.exists():
                    self.target_path.unlink()
            else:
                self.percentage = 100.0
                self.status = "completed"

        except Exception as e:
            self.status = "error"
            self.error_message = str(e)


class ROMManager:
    """Manages local ROM packages and downloads from online repositories."""

    def __init__(self, downloads_dir: Optional[Path] = None):
        self.downloads_dir = downloads_dir or DOWNLOADS_DIR
        self.downloads_dir.mkdir(parents=True, exist_ok=True)
        self.active_download: Optional[DownloadTask] = None
        self._inspection_cache: Dict[str, Dict[str, Any]] = {}

    def list_local_packages(self, extra_dir: Optional[Path] = None) -> List[Dict[str, Any]]:
        """Scan download directory and optional extra directory for flashable archives and images."""
        packages: List[Dict[str, Any]] = []
        scan_dirs = [self.downloads_dir]
        if extra_dir and extra_dir.exists() and extra_dir not in scan_dirs:
            scan_dirs.append(extra_dir)

        for s_dir in scan_dirs:
            for item in s_dir.glob("*"):
                if item.is_file() and item.suffix.lower() in [".zip", ".img", ".bin"]:
                    size_mb = round(item.stat().st_size / (1024 * 1024), 1)
                    pkg_info = self.inspect_package(item)
                    pkg_info["size_mb"] = size_mb
                    packages.append(pkg_info)

        return packages

    def inspect_package(self, file_path: Path) -> Dict[str, Any]:
        """Inspect a ROM or recovery archive without full decompression, using fast caching."""
        if not file_path.exists():
            return {"valid": False, "error": "File does not exist", "path": str(file_path)}

        stat = file_path.stat()
        cache_key = f"{file_path}_{stat.st_mtime}_{stat.st_size}"
        if cache_key in self._inspection_cache:
            return self._inspection_cache[cache_key]

        info = {
            "name": file_path.name,
            "path": str(file_path),
            "type": "unknown",  # recovery, rom_zip, gsi_img, boot_img
            "compatible_devices": [],
            "android_version": "",
            "build_id": "",
            "has_payload": False,
            "valid": True
        }

        suffix = file_path.suffix.lower()

        if suffix == ".img":
            lower_name = file_path.name.lower()
            if "twrp" in lower_name or "orangefox" in lower_name or "recovery" in lower_name:
                info["type"] = "recovery"
            elif "boot" in lower_name:
                info["type"] = "boot_img"
            elif "system" in lower_name or "gsi" in lower_name:
                info["type"] = "gsi_img"
            else:
                info["type"] = "partition_img"
            self._inspection_cache[cache_key] = info
            return info

        if suffix == ".zip":
            try:
                with zipfile.ZipFile(str(file_path), "r") as z:
                    namelist = z.namelist()
                    info["has_payload"] = "payload.bin" in namelist

                    # Check for standard ROM characteristics
                    if "payload.bin" in namelist or any(n.startswith("META-INF/") for n in namelist):
                        info["type"] = "rom_zip"
                    elif any("recovery" in n.lower() for n in namelist):
                        info["type"] = "recovery_zip"

                    # 1. Inspect META-INF/com/android/metadata (official Android OTA standard)
                    for meta_name in ["META-INF/com/android/metadata", "metadata"]:
                        if meta_name in namelist:
                            with z.open(meta_name) as f:
                                meta_content = f.read(4096).decode("utf-8", errors="ignore")
                                for line in meta_content.splitlines():
                                    if "=" in line:
                                        k, v = line.split("=", 1)
                                        k = k.strip().lower()
                                        v = v.strip()
                                        if k in ["pre-device", "post-build"]:
                                            for dev in v.replace(",", " ").split():
                                                if dev and dev not in info["compatible_devices"]:
                                                    info["compatible_devices"].append(dev)
                                        elif k == "post-build":
                                            info["build_id"] = v

                    # 2. Inspect updater-script if compatible_devices still empty
                    if not info["compatible_devices"]:
                        for name in namelist:
                            if "updater-script" in name:
                                with z.open(name) as f:
                                    content = f.read(2048).decode("utf-8", errors="ignore")
                                    for word in content.split('"'):
                                        if len(word) >= 3 and len(word) <= 15 and word.isalnum():
                                            if word not in ["ro", "product", "device", "boot", "build", "assert"]:
                                                if word not in info["compatible_devices"]:
                                                    info["compatible_devices"].append(word)
                                break
            except zipfile.BadZipFile:
                info["valid"] = False
                info["type"] = "corrupt_zip"
            except Exception:
                pass

        self._inspection_cache[cache_key] = info
        return info

    def calculate_checksum(self, file_path: Path, algorithm: str = "sha256") -> str:
        """Calculate SHA256 or MD5 checksum of a file for integrity verification."""
        hasher = hashlib.sha256() if algorithm == "sha256" else hashlib.md5()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                hasher.update(chunk)
        return hasher.hexdigest()

    def start_download(self, url: str, filename: Optional[str] = None) -> DownloadTask:
        """Initiate background download of a ROM or recovery image."""
        if not filename:
            # Extract filename from URL or assign default
            raw_name = url.split("?")[0].rstrip("/").split("/")[-1]
            filename = raw_name if raw_name else f"custom_rom_{int(time.time())}.zip"

        target_file = self.downloads_dir / filename
        task = DownloadTask(url, target_file, label=filename)
        self.active_download = task
        task.start()
        return task

    def get_download_status(self) -> Dict[str, Any]:
        """Return status dictionary of current download."""
        if not self.active_download:
            return {"active": False}

        task = self.active_download
        return {
            "active": task.status in ["downloading", "queued"],
            "status": task.status,
            "filename": task.label,
            "percentage": task.percentage,
            "downloaded_mb": round(task.downloaded_bytes / (1024 * 1024), 2),
            "total_mb": round(task.total_bytes / (1024 * 1024), 2) if task.total_bytes > 0 else 0,
            "speed_mbps": task.speed_mbps,
            "error_message": task.error_message,
            "path": str(task.target_path) if task.status == "completed" else None
        }

    def get_curated_sources(self) -> List[Dict[str, str]]:
        """Return curated list of trusted custom ROM & recovery portals."""
        return [
            {
                "name": "LineageOS (Official Builds)",
                "category": "ROM",
                "description": "Clean, pure open-source Android with long-term stability and wide device support.",
                "url": "https://download.lineageos.org/"
            },
            {
                "name": "PixelOS (Pixel Experience)",
                "category": "ROM",
                "description": "Clean Pixel UI with Google dialer, camera optimization, and smooth animations.",
                "url": "https://pixelos.net/"
            },
            {
                "name": "crDroid Android",
                "category": "ROM",
                "description": "Rich customization options, high performance, and outstanding battery life.",
                "url": "https://crdroid.net/"
            },
            {
                "name": "OrangeFox Recovery Project",
                "category": "Recovery",
                "description": "Modern Touch Recovery with dynamic theme engine, OpenRecoveryScript, and auto-OTA survival.",
                "url": "https://orangefox.download/"
            },
            {
                "name": "TWRP (TeamWin Recovery Project)",
                "category": "Recovery",
                "description": "Industry standard custom recovery for partition backups, sideloading, and zip flashing.",
                "url": "https://twrp.me/Devices/"
            },
            {
                "name": "Google Official Android GSIs",
                "category": "GSI",
                "description": "Official Generic System Images flashable on any Treble-compliant device.",
                "url": "https://developer.android.com/about/versions/14/gsi-release-notes"
            }
        ]
