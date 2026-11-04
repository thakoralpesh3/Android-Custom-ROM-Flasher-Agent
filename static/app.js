// DroidFlash Agent Web Dashboard Client Controller

let currentDevices = [];
let selectedDeviceSerial = null;
let pollTimer = null;

// Tab switcher
function switchRomTab(tabName) {
  document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
  document.querySelectorAll('.tab-panel').forEach(p => p.style.display = 'none');

  const activeBtn = document.getElementById(`tab-${tabName}`);
  const activePanel = document.getElementById(`panel-${tabName}`);

  if (activeBtn) activeBtn.classList.add('active');
  if (activePanel) activePanel.style.display = 'block';
}

// Initial status polling
async function fetchStatus() {
  try {
    const res = await fetch('/api/status');
    const data = await res.json();

    // 1. Check tools
    const toolsBanner = document.getElementById('tools-banner');
    if (!data.tools.ready) {
      toolsBanner.style.display = 'flex';
      document.getElementById('env-adb').innerText = 'Missing (Auto-installable)';
      document.getElementById('env-fastboot').innerText = 'Missing';
    } else {
      toolsBanner.style.display = 'none';
      document.getElementById('env-adb').innerText = data.tools.adb_version || 'Ready';
      document.getElementById('env-fastboot').innerText = data.tools.fastboot_version || 'Ready';
    }

    // 2. Devices
    currentDevices = data.devices || [];
    renderDeviceStatus(currentDevices);

    // 3. GitHub Auth
    const ghStatus = document.getElementById('gh-auth-status');
    if (data.github.authenticated) {
      ghStatus.innerHTML = `✅ Authenticated as <strong>${data.github.username}</strong>`;
      ghStatus.style.color = '#34d399';
    } else {
      ghStatus.innerHTML = `⚠️ GitHub CLI not signed in. Run 'gh auth login'`;
      ghStatus.style.color = '#fbbf24';
    }

    // 4. Download tracking
    renderDownloadStatus(data.download);

    // 5. Flashing logs & progress
    if (data.flashing.active) {
      fetchFlashLogs();
    }
  } catch (err) {
    console.error('Failed to poll status:', err);
  }
}

// Render connected phone details
function renderDeviceStatus(devices) {
  const badge = document.getElementById('device-badge');
  const statusText = document.getElementById('device-status-text');

  if (devices.length === 0) {
    badge.className = 'status-badge badge-offline';
    statusText.innerText = 'No Device Connected';
    document.getElementById('dev-model').innerText = '--';
    document.getElementById('dev-codename').innerText = '--';
    document.getElementById('dev-mode').innerText = '--';
    document.getElementById('dev-battery').innerText = '--';
    document.getElementById('dev-bootloader').innerText = '--';
    selectedDeviceSerial = null;
    return;
  }

  const dev = devices[0];
  selectedDeviceSerial = dev.serial;

  // Set mode badge color
  if (dev.mode === 'device') {
    badge.className = 'status-badge badge-online';
    statusText.innerText = 'Online (ADB)';
  } else if (dev.interface === 'fastboot' || dev.mode === 'fastboot' || dev.mode === 'fastbootd') {
    badge.className = 'status-badge badge-fastboot';
    statusText.innerText = dev.mode.toUpperCase();
  } else if (dev.mode === 'recovery' || dev.mode === 'sideload') {
    badge.className = 'status-badge badge-recovery';
    statusText.innerText = dev.mode.toUpperCase();
  } else {
    badge.className = 'status-badge badge-offline';
    statusText.innerText = dev.mode;
  }

  document.getElementById('dev-model').innerText = dev.model || 'Unknown';
  document.getElementById('dev-codename').innerText = dev.codename || 'N/A';
  document.getElementById('dev-mode').innerText = (dev.mode || '').toUpperCase();
  document.getElementById('dev-battery').innerText = dev.battery_level !== null ? `${dev.battery_level}%` : 'N/A';

  const blText = dev.unlocked === true ? 'Unlocked ✅' : (dev.unlocked === false ? 'Locked 🔒' : 'Unknown');
  document.getElementById('dev-bootloader').innerText = blText;
}

// Render local ROM packages
async function loadLocalPackages() {
  try {
    const res = await fetch('/api/roms/local');
    const data = await res.json();
    const select = document.getElementById('select-local-rom');
    select.innerHTML = '<option value="">-- Select detected local package --</option>';

    if (data.packages && data.packages.length > 0) {
      data.packages.forEach(pkg => {
        const opt = document.createElement('option');
        opt.value = pkg.path;
        opt.innerText = `${pkg.name} (${pkg.size_mb} MB) [${pkg.type}]`;
        select.appendChild(opt);
      });
    }
  } catch (err) {
    console.error('Failed to load local packages:', err);
  }
}

// Render curated ROM & Recovery sources
async function loadCuratedSources() {
  try {
    const res = await fetch('/api/roms/sources');
    const data = await res.json();
    const container = document.getElementById('sources-container');
    container.innerHTML = '';

    data.sources.forEach(src => {
      const card = document.createElement('div');
      card.className = 'source-card';
      card.innerHTML = `
        <div>
          <div class="source-title">${src.name} <span style="font-size: 0.75rem; color: var(--accent-cyan); font-weight: normal;">[${src.category}]</span></div>
          <div class="source-desc">${src.description}</div>
        </div>
        <a href="${src.url}" target="_blank" class="btn btn-secondary" style="padding: 0.4rem 0.8rem; font-size: 0.8rem;">Open ↗</a>
      `;
      container.appendChild(card);
    });
  } catch (err) {
    console.error('Failed to load curated sources:', err);
  }
}

// Download status tracker
function renderDownloadStatus(status) {
  const box = document.getElementById('download-progress-box');
  if (!status || !status.active) {
    if (status && status.status === 'completed') {
      box.style.display = 'block';
      document.getElementById('dl-filename').innerText = `Downloaded: ${status.filename}`;
      document.getElementById('dl-stats').innerText = '100% (Ready to Flash)';
      document.getElementById('dl-progress-bar').style.width = '100%';
      document.getElementById('dl-subtext').innerText = `Saved in downloads directory.`;
      loadLocalPackages();
    }
    return;
  }

  box.style.display = 'block';
  document.getElementById('dl-filename').innerText = `Downloading ${status.filename}...`;
  document.getElementById('dl-stats').innerText = `${status.percentage}% (${status.downloaded_mb} / ${status.total_mb} MB)`;
  document.getElementById('dl-progress-bar').style.width = `${status.percentage}%`;
  document.getElementById('dl-subtext').innerText = `Speed: ${status.speed_mbps} MB/s`;
}

// Start online download
document.getElementById('btn-start-download').addEventListener('click', async () => {
  const url = document.getElementById('input-download-url').value.trim();
  const filename = document.getElementById('input-download-filename').value.trim();

  if (!url) {
    alert('Please enter a valid download URL.');
    return;
  }

  try {
    const res = await fetch('/api/download/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url, filename })
    });
    const data = await res.json();
    alert(data.message);
  } catch (err) {
    alert('Download request failed: ' + err);
  }
});

// Auto-install tools button
document.getElementById('btn-install-tools').addEventListener('click', async () => {
  const btn = document.getElementById('btn-install-tools');
  btn.disabled = true;
  btn.innerText = 'Installing...';

  try {
    const res = await fetch('/api/setup-tools', { method: 'POST' });
    const data = await res.json();
    alert(data.message);
    fetchStatus();
  } catch (err) {
    alert('Failed to install tools: ' + err);
  } finally {
    btn.disabled = false;
    btn.innerText = 'Auto-Install Google Tools';
  }
});

// Device Reboot Actions
async function rebootDevice(target) {
  if (!selectedDeviceSerial) {
    alert('No device connected.');
    return;
  }

  try {
    const res = await fetch('/api/devices/reboot', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ serial: selectedDeviceSerial, target })
    });
    const data = await res.json();
    alert(data.message);
  } catch (err) {
    alert('Reboot failed: ' + err);
  }
}

// Unlock Bootloader
async function unlockBootloader() {
  if (!selectedDeviceSerial) {
    alert('No device connected. Please connect device in Fastboot mode.');
    return;
  }

  if (!confirm('WARNING: Unlocking bootloader will wipe all data on the phone. Do you wish to continue?')) {
    return;
  }

  try {
    const res = await fetch('/api/devices/unlock', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ serial: selectedDeviceSerial })
    });
    const data = await res.json();
    alert(data.message);
  } catch (err) {
    alert('Unlock command failed: ' + err);
  }
}

// Start Automated Flash Pipeline
document.getElementById('btn-start-flash').addEventListener('click', async () => {
  if (!selectedDeviceSerial) {
    alert('No Android smartphone detected. Please connect phone via USB with USB Debugging enabled.');
    return;
  }

  const selectedLocal = document.getElementById('select-local-rom').value;
  const customPath = document.getElementById('input-custom-rom-path').value.trim();
  const romPath = selectedLocal || customPath;

  if (!romPath) {
    alert('Please select or specify a Custom ROM package (.zip or .img).');
    return;
  }

  const recoveryPath = document.getElementById('input-custom-recovery-path').value.trim();
  const wipeData = document.getElementById('check-wipe-data').checked;

  if (!confirm(`Are you ready to install custom ROM:\n${romPath}\n\nMake sure your battery is charged and data is backed up!`)) {
    return;
  }

  try {
    const res = await fetch('/api/flash/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        serial: selectedDeviceSerial,
        rom_path: romPath,
        recovery_path: recoveryPath,
        wipe_data: wipeData
      })
    });
    const data = await res.json();
    if (!data.success) {
      alert('Error: ' + data.message);
    } else {
      // Start polling logs rapidly
      pollFlashLogsFast();
    }
  } catch (err) {
    alert('Failed to start flashing: ' + err);
  }
});

// Fetch and stream logs
async function fetchFlashLogs() {
  try {
    const res = await fetch('/api/flash/logs');
    const data = await res.json();

    document.getElementById('flash-step-label').innerText = data.step || 'Idle';
    document.getElementById('flash-pct-label').innerText = `${data.progress || 0}%`;
    document.getElementById('flash-progress-bar').style.width = `${data.progress || 0}%`;

    const term = document.getElementById('terminal-body');
    if (data.logs && data.logs.length > 0) {
      term.innerHTML = data.logs.map(line => {
        let cls = 'log-INFO';
        if (line.includes('[SUCCESS]')) cls = 'log-SUCCESS';
        else if (line.includes('[WARN]')) cls = 'log-WARN';
        else if (line.includes('[ERROR]')) cls = 'log-ERROR';
        else if (line.includes('[SETUP]')) cls = 'log-SETUP';
        return `<div class="log-line ${cls}">${escapeHtml(line)}</div>`;
      }).join('');
      term.scrollTop = term.scrollHeight;
    }
  } catch (err) {
    console.error('Failed to fetch flash logs:', err);
  }
}

function pollFlashLogsFast() {
  const interval = setInterval(async () => {
    await fetchFlashLogs();
    const res = await fetch('/api/status');
    const data = await res.json();
    if (!data.flashing.active) {
      clearInterval(interval);
    }
  }, 1000);
}

function escapeHtml(text) {
  return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

// GitHub Automated Sync
document.getElementById('btn-sync-github').addEventListener('click', async () => {
  const btn = document.getElementById('btn-sync-github');
  const repoName = document.getElementById('gh-repo-name').value.trim();
  const commitMsg = document.getElementById('gh-commit-msg').value.trim();
  const isPrivate = document.getElementById('gh-private').checked;

  btn.disabled = true;
  btn.innerText = 'Syncing with GitHub...';

  try {
    const res = await fetch('/api/github/sync', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        repo_name: repoName,
        commit_message: commitMsg,
        is_private: isPrivate
      })
    });
    const data = await res.json();
    alert(data.message);
    fetchStatus();
  } catch (err) {
    alert('GitHub sync failed: ' + err);
  } finally {
    btn.disabled = false;
    btn.innerText = '🚀 Sync & Upload to GitHub';
  }
});

document.getElementById('btn-open-github-modal').addEventListener('click', () => {
  document.getElementById('gh-repo-name').scrollIntoView({ behavior: 'smooth' });
});

document.getElementById('btn-refresh-devices').addEventListener('click', () => {
  fetchStatus();
});

document.getElementById('btn-clear-logs').addEventListener('click', () => {
  document.getElementById('terminal-body').innerHTML = '<div class="log-line log-INFO">[00:00:00] [INFO] Logs cleared.</div>';
});

// Initialization
window.addEventListener('DOMContentLoaded', () => {
  fetchStatus();
  loadLocalPackages();
  loadCuratedSources();
  pollTimer = setInterval(fetchStatus, 3000);
});
