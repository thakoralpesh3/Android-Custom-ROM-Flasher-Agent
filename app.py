#!/usr/bin/env python3
"""
Custom ROM Flasher Agent - Main Application & Server
Provides an automated engine, Web GUI Dashboard, and CLI Terminal Wizard for
installing custom ROMs, managing downloads, detecting Android devices, and syncing to GitHub.
"""

import sys
import os
import json
import mimetypes
import argparse
import webbrowser
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

# Add root directory to sys.path
BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from core.adb_manager import ADBManager
from core.device_detector import DeviceDetector
from core.rom_manager import ROMManager
from core.flash_engine import FlashEngine
from core.github_sync import GitHubSync

# Global Instances
adb_mgr = ADBManager()
detector = DeviceDetector(adb_mgr)
rom_mgr = ROMManager()
flasher = FlashEngine(adb_mgr, detector)
gh_sync = GitHubSync()


class FlasherHTTPRequestHandler(BaseHTTPRequestHandler):
    """Handles REST API and static file requests."""

    def _send_json(self, data: dict, status: int = 200):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _serve_file(self, file_path: Path):
        if not file_path.exists() or not file_path.is_file():
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"404 Not Found")
            return

        mime_type, _ = mimetypes.guess_type(str(file_path))
        if not mime_type:
            mime_type = "application/octet-stream"

        try:
            with open(file_path, "rb") as f:
                content = f.read()
            self.send_response(200)
            self.send_header("Content-Type", mime_type)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        except Exception as e:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(f"500 Internal Error: {e}".encode("utf-8"))

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        # Static Web UI Routes
        if path == "/" or path == "/index.html":
            self._serve_file(BASE_DIR / "static" / "index.html")
            return
        elif path.startswith("/static/"):
            rel_path = path[len("/static/"):]
            self._serve_file(BASE_DIR / "static" / rel_path)
            return

        # API Routes
        if path == "/api/status":
            auth = gh_sync.check_gh_auth()
            tools_info = adb_mgr.get_version_info()
            devices = detector.scan_devices()
            self._send_json({
                "tools": tools_info,
                "devices": devices,
                "device_count": len(devices),
                "github": auth,
                "download": rom_mgr.get_download_status(),
                "flashing": {
                    "active": flasher.is_flashing,
                    "step": flasher.current_step,
                    "progress": flasher.progress_pct
                }
            })
            return

        elif path == "/api/devices":
            devices = detector.scan_devices()
            self._send_json({"devices": devices})
            return

        elif path == "/api/roms/local":
            packages = rom_mgr.list_local_packages(extra_dir=BASE_DIR)
            self._send_json({"packages": packages})
            return

        elif path == "/api/roms/sources":
            sources = rom_mgr.get_curated_sources()
            self._send_json({"sources": sources})
            return

        elif path == "/api/download/status":
            self._send_json(rom_mgr.get_download_status())
            return

        elif path == "/api/flash/logs":
            self._send_json({
                "flashing": flasher.is_flashing,
                "step": flasher.current_step,
                "progress": flasher.progress_pct,
                "logs": flasher.log_history
            })
            return

        # 404 for unknown route
        self.send_response(404)
        self.end_headers()
        self.wfile.write(b"Not Found")

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
        try:
            payload = json.loads(body)
        except Exception:
            payload = {}

        if path == "/api/setup-tools":
            def _log(msg):
                flasher.log(msg, "SETUP")
            success, msg = adb_mgr.download_platform_tools(progress_callback=_log)
            self._send_json({"success": success, "message": msg})
            return

        elif path == "/api/devices/reboot":
            target = payload.get("target", "system")
            serial = payload.get("serial")
            success, msg = detector.reboot_device(target, serial)
            self._send_json({"success": success, "message": msg})
            return

        elif path == "/api/devices/unlock":
            serial = payload.get("serial")
            code, out, err = adb_mgr.run_fastboot(["flashing", "unlock"], serial=serial)
            if code != 0:
                # Try legacy OEM unlock
                code, out, err = adb_mgr.run_fastboot(["oem", "unlock"], serial=serial)

            msg = out if code == 0 else err
            self._send_json({
                "success": (code == 0),
                "message": msg or "Bootloader unlock signal sent. Confirm on device screen!"
            })
            return

        elif path == "/api/download/start":
            url = payload.get("url", "").strip()
            filename = payload.get("filename", "").strip() or None
            if not url:
                self._send_json({"success": False, "message": "Missing download URL."}, 400)
                return

            task = rom_mgr.start_download(url, filename)
            self._send_json({"success": True, "message": f"Download initiated for {task.label}"})
            return

        elif path == "/api/flash/start":
            if flasher.is_flashing:
                self._send_json({"success": False, "message": "A flashing operation is already running."}, 400)
                return

            serial = payload.get("serial", "")
            rom_path = payload.get("rom_path", "")
            recovery_path = payload.get("recovery_path") or None
            wipe_data = payload.get("wipe_data", True)
            addons = payload.get("addons", [])

            if not rom_path:
                self._send_json({"success": False, "message": "ROM path is required."}, 400)
                return

            flasher.start_flash_pipeline_async(
                serial=serial,
                rom_path=rom_path,
                recovery_path=recovery_path,
                wipe_data=wipe_data,
                addons=addons
            )
            self._send_json({"success": True, "message": "Flashing process initiated."})
            return

        elif path == "/api/github/sync":
            repo_name = payload.get("repo_name", "Android-Custom-ROM-Flasher-Agent").strip()
            commit_msg = payload.get("commit_message", "feat: update custom rom flasher agent").strip()
            is_priv = payload.get("is_private", False)

            success, msg = gh_sync.auto_sync_to_github(
                repo_name=repo_name,
                commit_message=commit_msg,
                is_private=is_priv
            )
            self._send_json({"success": success, "message": msg})
            return

        self.send_response(404)
        self.end_headers()


def run_cli_wizard():
    """Terminal interactive wizard for quick flashing and environment management."""
    print("================================================================")
    print("      🚀 DROIDFLASH AGENT - ANDROID CUSTOM ROM FLASHER          ")
    print("================================================================")

    # 1. Check tools
    if not adb_mgr.is_ready():
        print("⚠️ Android Platform Tools (adb/fastboot) not found!")
        choice = input("Would you like to auto-download official Google Platform Tools? [y/N]: ").strip().lower()
        if choice == 'y':
            print("Downloading...")
            ok, msg = adb_mgr.download_platform_tools(lambda m: print(f"  {m}"))
            print(f"Result: {msg}")
            if not ok:
                return
        else:
            print("Cannot continue without adb/fastboot.")
            return

    # 2. Check devices
    print("\nScanning for connected Android devices...")
    devices = detector.scan_devices()
    if not devices:
        print("❌ No Android devices found.")
        print("Please enable 'USB Debugging' and connect phone via USB cable.")
        return

    print(f"\nFound {len(devices)} device(s):")
    for idx, d in enumerate(devices):
        print(f" [{idx + 1}] {d.get('model')} ({d.get('serial')}) - Mode: {d.get('mode')} - Battery: {d.get('battery_level', 'N/A')}%")

    sel_idx = 0
    if len(devices) > 1:
        sel = input("Select device number [1]: ").strip()
        sel_idx = int(sel) - 1 if sel.isdigit() and 1 <= int(sel) <= len(devices) else 0

    selected_dev = devices[sel_idx]
    print(f"Selected: {selected_dev.get('model')} ({selected_dev.get('serial')})")

    # 3. Actions menu
    print("\nOptions:")
    print(" 1. Flash a Custom ROM (Recovery Sideload or Fastboot)")
    print(" 2. Reboot device (System / Recovery / Fastboot / FastbootD)")
    print(" 3. Unlock Bootloader (fastboot flashing unlock)")
    print(" 4. Upload & Sync Agent to GitHub")
    print(" 5. Launch Web GUI Dashboard")

    opt = input("\nEnter choice [1-5]: ").strip()

    if opt == "1":
        rom_path = input("Enter path to custom ROM .zip or .img file: ").strip()
        if not Path(rom_path).exists():
            print(f"Error: File '{rom_path}' not found.")
            return
        rec_path = input("Enter custom recovery .img file (optional, leave blank to skip): ").strip()
        wipe = input("Wipe UserData / Factory Reset? (Recommended) [Y/n]: ").strip().lower() != 'n'

        print("\nStarting Flashing Pipeline in foreground...")
        flasher._run_pipeline(
            serial=selected_dev["serial"],
            rom_path=rom_path,
            recovery_path=rec_path if rec_path else None,
            wipe_data=wipe,
            addons=[],
            on_complete=lambda ok, msg: print(f"\nCompleted: ok={ok}, message={msg}")
        )

    elif opt == "2":
        print("Reboot targets: system, recovery, bootloader, fastbootd")
        tgt = input("Enter target [recovery]: ").strip() or "recovery"
        ok, msg = detector.reboot_device(tgt, selected_dev["serial"])
        print(msg)

    elif opt == "3":
        code, out, err = adb_mgr.run_fastboot(["flashing", "unlock"], serial=selected_dev["serial"])
        print(out or err)

    elif opt == "4":
        repo_name = input("Enter GitHub repository name [Android-Custom-ROM-Flasher-Agent]: ").strip() or "Android-Custom-ROM-Flasher-Agent"
        print("Syncing with GitHub...")
        ok, msg = gh_sync.auto_sync_to_github(repo_name=repo_name)
        print(f"Result: {msg}")

    elif opt == "5":
        start_web_server(port=8765, open_browser=True)


def start_web_server(port: int = 8765, open_browser: bool = True):
    """Start local web dashboard server."""
    # Ensure platform tools if not present
    if not adb_mgr.is_ready():
        print("Platform tools not found. Auto-fetching official Google Platform Tools...")
        adb_mgr.download_platform_tools(lambda m: print(f"  {m}"))

    server_address = ("127.0.0.1", port)
    httpd = HTTPServer(server_address, FlasherHTTPRequestHandler)
    dashboard_url = f"http://127.0.0.1:{port}"

    print(f"\n================================================================")
    print(f"  🚀 DroidFlash Web Dashboard running at: {dashboard_url}")
    print(f"  Press Ctrl+C to stop the server.")
    print(f"================================================================\n")

    if open_browser:
        webbrowser.open(dashboard_url)

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping DroidFlash Web Dashboard...")
        httpd.server_close()


def main():
    parser = argparse.ArgumentParser(description="Android Custom ROM Flasher Agent")
    parser.add_argument("--gui", action="store_true", help="Launch Web GUI Dashboard (Default)")
    parser.add_argument("--wizard", "--cli", action="store_true", help="Launch Interactive Terminal Wizard")
    parser.add_argument("--port", type=int, default=8765, help="Port for Web GUI Dashboard")
    parser.add_argument("--no-browser", action="store_true", help="Do not open browser automatically")
    parser.add_argument("--sync-github", action="store_true", help="Automatically commit and sync code to GitHub")
    parser.add_argument("--setup-tools", action="store_true", help="Auto-download official Google Platform Tools")
    parser.add_argument("--check", action="store_true", help="Check environment and connected devices")

    args = parser.parse_args()

    if args.setup_tools:
        print("Ensuring Android Platform Tools...")
        ok, msg = adb_mgr.download_platform_tools(lambda m: print(f"  {m}"))
        print(msg)
        return

    if args.check:
        print("Environment Status:")
        info = adb_mgr.get_version_info()
        print(f"  ADB: {info['adb_path']} ({info['adb_version']})")
        print(f"  Fastboot: {info['fastboot_path']} ({info['fastboot_version']})")
        devs = detector.scan_devices()
        print(f"\nConnected Devices: {len(devs)}")
        for d in devs:
            print(f"  - {d.get('model')} ({d.get('serial')}) in mode: {d.get('mode')}")
        gh = gh_sync.check_gh_auth()
        print(f"\nGitHub CLI: {'Authenticated as ' + gh['username'] if gh['authenticated'] else 'Not Authenticated'}")
        return

    if args.sync_github:
        print("Triggering Automated GitHub Sync...")
        ok, msg = gh_sync.auto_sync_to_github()
        print(f"Result: {msg}")
        return

    if args.wizard:
        run_cli_wizard()
        return

    # Default to GUI
    start_web_server(port=args.port, open_browser=not args.no_browser)


if __name__ == "__main__":
    main()
