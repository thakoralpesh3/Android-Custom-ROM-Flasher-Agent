# 📱 DroidFlash AI - Android Custom ROM Installation & Flashing Agent

An autonomous agent and cross-interface suite designed to command and execute the complete Custom ROM installation pipeline on Android smartphones, with built-in online ROM downloading, local package management, recovery deployment, safety checks, and 1-click automated GitHub repository creation and synchronization.

![DroidFlash Banner](static/icons/app_icon.png)

---

## ✨ Features

- **Desktop Launcher**: Double-click the `DroidFlash AI` desktop shortcut on your desktop to launch either the Cyber-styled Web Dashboard or the Interactive Terminal Wizard.
- **Automated Platform Tools**: Detects or automatically downloads the official Google Android Platform-Tools (`adb` & `fastboot`) for Linux into a sandboxed environment.
- **Smart Device Detection**:
  - Live inspection of USB-connected Android smartphones.
  - Detects hardware codename (e.g. `cheeseburger`, `alioth`), model name, Android version, battery level, bootloader lock state, and connection interface (`adb`, `fastboot`, `fastbootd`, `recovery`, `sideload`).
- **Flexible ROM Source Modes**:
  - **Local Custom ROMs**: Flash local `.zip` packages (LineageOS, PixelOS, crDroid, EvolutionX, ArrowOS, etc.) or `.img` partition images (GSI system, TWRP, OrangeFox, boot images).
  - **Online Direct Downloader**: Paste any direct download URL (SourceForge, GitHub releases, AndroidFileHost, custom servers) with background streaming, live progress, speed metrics, and auto-registration into the flasher.
  - **Curated ROM Repositories**: Direct catalog access for verified ROM and Custom Recovery distributions.
- **Autonomous Flashing Engine**:
  - Handles complete workflow: pre-flight checks (battery check, codename safety validation), bootloader unlock commands, custom recovery flashing, factory reset / UserData wiping, recovery sideloading via ADB, and automatic reboot.
  - Real-time execution console streaming terminal outputs with color-coded severity tags.
- **Automatic GitHub Sync & Upload**:
  - Seamlessly creates a GitHub repository and pushes the entire codebase with 1 click or command using the GitHub CLI (`gh`).
  - Pre-configured `.gitignore` prevents uploading multi-gigabyte ROM files while keeping scripts, agents, and device profiles synced.

---

## 🚀 Quick Start

### 1. Launch from Desktop
Double click the **DroidFlash AI - Custom ROM Agent** shortcut on your Linux Desktop, or right-click to choose:
- 🚀 Open DroidFlash Web Dashboard
- 🧙‍♂️ Interactive Terminal Wizard
- 🐙 Auto-Upload & Sync to GitHub
- 🔍 Check Device & Platform Tools
- 📁 Open ROM Downloads Folder

### 2. Launch from Terminal
```bash
cd "/media/alpesh/Software & Work/Agents/Custom_Roms"

# Launch Web GUI Dashboard (default)
./launch_agent.sh --gui

# Or start the Interactive Terminal Wizard
./launch_agent.sh --wizard

# Or test environment and connected devices
./launch_agent.sh --check

# Or automatically sync agent codebase to GitHub
./launch_agent.sh --sync-github
```

---

## ⚡ Flashing Workflow Guide

1. **Enable Developer Options & USB Debugging**:
   - On your phone: Go to `Settings` -> `About phone` -> tap `Build number` 7 times.
   - Go to `Settings` -> `System` -> `Developer options`.
   - Enable **OEM Unlocking** and **USB Debugging**.
2. **Connect phone via USB**:
   - Connect phone to your PC via a USB data cable.
   - Tap **"Always allow from this computer"** when the RSA fingerprint prompt appears on phone.
3. **Select or Download ROM**:
   - In DroidFlash Dashboard, choose **Local Custom ROM** or enter a direct URL under **Download ROM Online**.
4. **Click "Start Automated ROM Installation"**:
   - The agent handles the state transitions (Reboot to bootloader / recovery -> Wipe data -> Sideload ROM -> Reboot system).

---

## 🐙 Auto-Syncing to GitHub

DroidFlash includes automated Git and GitHub CLI integration:
```bash
./launch_agent.sh --sync-github
```
Or click the **🐙 Upload to GitHub** button inside the web dashboard. The agent will initialize git, stage code, create the remote repository on GitHub via `gh`, and push the commits automatically!
