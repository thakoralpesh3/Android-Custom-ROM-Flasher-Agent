// DroidFlash Agent Web Dashboard Client Controller
// Enhanced with Anti-Brick Safety Scorecard, SSE Real-Time Logs, Stepper & Dropzone

let currentDevices = [];
let selectedDeviceSerial = null;
let pollTimer = null;
let eventSource = null;
let currentScorecard = null;
let rawLogEntries = [];

// Tab switcher
function switchRomTab(tabName) {
  document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
  document.querySelectorAll('.tab-panel').forEach(p => p.style.display = 'none');

  const activeBtn = document.getElementById(`tab-${tabName}`);
  const activePanel = document.getElementById(`panel-${tabName}`);

  if (activeBtn) activeBtn.classList.add('active');
  if (activePanel) activePanel.style.display = 'block');
}

// Stepper Progress Updates
function updateStepper(stepIndex) {
  for (let i = 1; i <= 5; i++) {
    const stepEl = document.getElementById(`step-${i}`);
    const lineEl = document.getElementById(`line-${i}`);
    if (!stepEl) continue;

    if (i < stepIndex) {
      stepEl.className = 'stepper-step completed';
      if (lineEl) lineEl.className = 'stepper-line active';
    } else if (i === stepIndex) {
      stepEl.className = 'stepper-step active';
      if (lineEl) lineEl.className = 'stepper-line';
    } else {
      stepEl.className = 'stepper-step';
      if (lineEl) lineEl.className = 'stepper-line';
    }
  }
}

// Map pipeline step name to stepper index
function syncStepperWithStepName(stepName) {
  const s = (stepName || '').toLowerCase();
  if (!s || s === 'idle' || s === 'ready') {
    updateStepper(currentDevices.length > 0 ? 2 : 1);
  } else if (s.includes('pre-flight') || s.includes('safety')) {
    updateStepper(2);
  } else if (s.includes('recovery') || s.includes('bootloader') || s.includes('wipe')) {
    updateStepper(3);
  } else if (s.includes('flashing') || s.includes('sideload') || s.includes('addon')) {
    updateStepper(4);
  } else if (s.includes('reboot') || s.includes('completed')) {
    updateStepper(5);
  }
}

// SSE Real-Time Log Streaming
function initSSEStream() {
  if (eventSource) {
    eventSource.close();
  }

  try {
    eventSource = new EventSource('/api/flash/stream');

    eventSource.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data);
        if (data.type === 'init') {
          if (data.logs) {
            rawLogEntries = data.logs;
            renderFilteredLogs();
          }
          updateFlashStatusUI(data.flashing, data.step, data.progress);
        } else if (data.type === 'log') {
          rawLogEntries.push(data.entry);
          appendLogLine(data.entry);
          updateFlashStatusUI(true, data.step, data.progress);
        }
      } catch (err) {
        // Heartbeat or raw text
      }
    };

    eventSource.onerror = () => {
      const ind = document.getElementById('sse-indicator');
      if (ind) ind.style.background = '#f59e0b';
    };

    eventSource.onopen = () => {
      const ind = document.getElementById('sse-indicator');
      if (ind) ind.style.background = '#34d399';
    };
  } catch (err) {
    console.warn('SSE failed, fallback to polling', err);
  }
}

function updateFlashStatusUI(flashing, step, progress) {
  const lblStep = document.getElementById('flash-step-label');
  const lblPct = document.getElementById('flash-pct-label');
  const pBar = document.getElementById('flash-progress-bar');
  const btnStart = document.getElementById('btn-start-flash');
  const btnCancel = document.getElementById('btn-cancel-flash');

  if (lblStep) lblStep.innerText = step || 'Ready';
  if (lblPct) lblPct.innerText = `${progress || 0}%`;
  if (pBar) pBar.style.width = `${progress || 0}%`;

  if (flashing) {
    if (btnStart) {
      btnStart.disabled = true;
      btnStart.innerText = `⏳ Installing (${step})...`;
    }
    if (btnCancel) btnCancel.style.display = 'inline-flex';
  } else {
    if (btnStart) {
      btnStart.disabled = false;
      btnStart.innerText = '🚀 Start Automated ROM Installation';
    }
    if (btnCancel) btnCancel.style.display = 'none';
  }

  syncStepperWithStepName(step);
}

// Initial and recurring status polling
async function fetchStatus() {
  try {
    const res = await fetch('/api/status');
    const data = await res.json();

    // 1. Check tools
    const toolsBanner = document.getElementById('tools-banner');
    if (!data.tools.ready) {
      if (toolsBanner) toolsBanner.style.display = 'flex';
      document.getElementById('env-adb').innerText = 'Missing (Auto-installable)';
      document.getElementById('env-fastboot').innerText = 'Missing';
    } else {
      if (toolsBanner) toolsBanner.style.display = 'none';
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

    // 5. Update flash status UI
    updateFlashStatusUI(data.flashing.active, data.flashing.step, data.flashing.progress);

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
    updateStepper(1);
    const card = document.getElementById('safety-card');
    if (card) card.style.display = 'none';
    return;
  }

  const dev = devices[0];
  selectedDeviceSerial = dev.serial;

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

  runSafetyPrecheck();
}

// Run Anti-Brick Safety Check against selected ROM and device
async function runSafetyPrecheck() {
  const selectedLocal = document.getElementById('select-local-rom').value;
  const customPath = document.getElementById('input-custom-rom-path').value.trim();
  const romPath = selectedLocal || customPath;

  if (!romPath || !selectedDeviceSerial) {
    const card = document.getElementById('safety-card');
    if (card) card.style.display = 'none';
    return;
  }

  try {
    const res = await fetch('/api/flash/precheck', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ serial: selectedDeviceSerial, rom_path: romPath })
    });
    const data = await res.json();
    if (!data.success) return;

    currentScorecard = data.scorecard;
    const card = document.getElementById('safety-card');
    const badge = document.getElementById('safety-badge');
    const summary = document.getElementById('safety-summary');
    const blkBox = document.getElementById('safety-blockers-box');
    const warnBox = document.getElementById('safety-warnings-box');

    card.style.display = 'block';

    const devCodename = data.scorecard.details.device_codename || 'unknown';
    const romCompat = data.scorecard.details.rom_compatible_devices || [];
    const bat = data.scorecard.details.battery;

    if (data.scorecard.safe) {
      card.style.borderColor = 'rgba(52, 211, 153, 0.4)';
      badge.className = 'status-badge badge-online';
      badge.innerText = 'SAFE TO FLASH';
    } else {
      card.style.borderColor = 'rgba(244, 63, 94, 0.5)';
      badge.className = 'status-badge badge-offline';
      badge.innerText = 'BLOCKED (ANTI-BRICK)';
    }

    summary.innerHTML = `
      <div><strong>Target Codename:</strong> ${devCodename} ${data.scorecard.details.codename_match ? '✅ MATCH' : ''}</div>
      <div><strong>ROM Compatible List:</strong> ${romCompat.length ? romCompat.join(', ') : 'Generic / Universal'}</div>
      <div><strong>Battery Level:</strong> ${bat !== null ? bat + '%' : 'N/A'} ${bat && bat >= 40 ? '✅ SAFE' : (bat ? '⚠️ LOW' : '')}</div>
    `;

    if (data.scorecard.blockers.length > 0) {
      blkBox.style.display = 'block';
      blkBox.innerHTML = '<strong>❌ Critical Blockers:</strong><ul style="margin-left: 1.2rem; margin-top: 0.2rem;">' +
        data.scorecard.blockers.map(b => `<li>${escapeHtml(b)}</li>`).join('') + '</ul>';
    } else {
      blkBox.style.display = 'none';
    }

    if (data.scorecard.warnings.length > 0) {
      warnBox.style.display = 'block';
      warnBox.innerHTML = '<strong>⚠️ Safety Warnings:</strong><ul style="margin-left: 1.2rem; margin-top: 0.2rem;">' +
        data.scorecard.warnings.map(w => `<li>${escapeHtml(w)}</li>`).join('') + '</ul>';
    } else {
      warnBox.style.display = 'none';
    }

    updateStepper(2);

  } catch (err) {
    console.error('Safety check failed:', err);
  }
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

// Cancel Flashing
async function cancelFlashing() {
  if (!confirm('Are you sure you want to request cancellation of the flashing process?')) return;
  try {
    const res = await fetch('/api/flash/cancel', { method: 'POST' });
    const data = await res.json();
    alert(data.message);
  } catch (err) {
    alert('Cancel request failed: ' + err);
  }
}

// Take Safety Snapshot
document.getElementById('btn-backup-device').addEventListener('click', async () => {
  if (!selectedDeviceSerial) {
    alert('Please connect a phone via USB first.');
    return;
  }

  const btn = document.getElementById('btn-backup-device');
  btn.disabled = true;
  btn.innerText = 'Creating Backup...';

  try {
    const res = await fetch('/api/devices/backup', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ serial: selectedDeviceSerial })
    });
    const data = await res.json();
    alert(data.message);
  } catch (err) {
    alert('Backup failed: ' + err);
  } finally {
    btn.disabled = false;
    btn.innerText = '🛡️ Safety Snapshot';
  }
});

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
  const forceFlash = document.getElementById('check-force-flash').checked;

  if (currentScorecard && !currentScorecard.safe && !forceFlash) {
    alert('FLASHER BLOCKED: Critical Anti-Brick blockers are active! To proceed anyway at your own risk, check "Override Anti-Brick Blocker".');
    return;
  }

  if (!confirm(`Are you ready to install custom ROM:
${romPath}

Make sure your phone is charged and data is backed up!`)) {
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
        wipe_data: wipeData,
        force: forceFlash
      })
    });
    const data = await res.json();
    if (!data.success) {
      alert('Error: ' + data.message);
    }
  } catch (err) {
    alert('Failed to start flashing: ' + err);
  }
});

// Log Rendering and Filtering
function renderFilteredLogs() {
  const filter = document.getElementById('select-log-filter').value;
  const term = document.getElementById('terminal-body');

  const filtered = rawLogEntries.filter(line => {
    if (filter === 'ALL') return true;
    if (filter === 'ERROR') return line.includes('[ERROR]') || line.includes('BLOCKED');
    if (filter === 'WARN') return line.includes('[WARN]');
    if (filter === 'SUCCESS') return line.includes('[SUCCESS]');
    if (filter === 'ADB') return line.includes('[ADB]') || line.includes('fastboot');
    return true;
  });

  term.innerHTML = filtered.map(line => {
    let cls = 'log-INFO';
    if (line.includes('[SUCCESS]')) cls = 'log-SUCCESS';
    else if (line.includes('[WARN]')) cls = 'log-WARN';
    else if (line.includes('[ERROR]')) cls = 'log-ERROR';
    else if (line.includes('[SETUP]')) cls = 'log-SETUP';
    return `<div class="log-line ${cls}">${escapeHtml(line)}</div>`;
  }).join('');

  term.scrollTop = term.scrollHeight;
}

function appendLogLine(line) {
  const filter = document.getElementById('select-log-filter').value;
  let shouldShow = true;
  if (filter === 'ERROR' && !(line.includes('[ERROR]') || line.includes('BLOCKED'))) shouldShow = false;
  if (filter === 'WARN' && !line.includes('[WARN]')) shouldShow = false;
  if (filter === 'SUCCESS' && !line.includes('[SUCCESS]')) shouldShow = false;
  if (filter === 'ADB' && !(line.includes('[ADB]') || line.includes('fastboot'))) shouldShow = false;

  if (shouldShow) {
    const term = document.getElementById('terminal-body');
    let cls = 'log-INFO';
    if (line.includes('[SUCCESS]')) cls = 'log-SUCCESS';
    else if (line.includes('[WARN]')) cls = 'log-WARN';
    else if (line.includes('[ERROR]')) cls = 'log-ERROR';
    else if (line.includes('[SETUP]')) cls = 'log-SETUP';

    const div = document.createElement('div');
    div.className = `log-line ${cls}`;
    div.innerText = line;
    term.appendChild(div);
    term.scrollTop = term.scrollHeight;
  }
}

document.getElementById('select-log-filter').addEventListener('change', renderFilteredLogs);

// Export Logs to .txt
document.getElementById('btn-download-logs').addEventListener('click', () => {
  if (rawLogEntries.length === 0) {
    alert('Log is empty.');
    return;
  }
  const blob = new Blob([rawLogEntries.join('\n')], { type: 'text/plain' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `droidflash_log_${new Date().toISOString().replace(/[:.]/g, '_')}.txt`;
  a.click();
});

function escapeHtml(text) {
  return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

// Drag & Drop Setup
const dropzone = document.getElementById('rom-dropzone');
if (dropzone) {
  ['dragenter', 'dragover'].forEach(eventName => {
    dropzone.addEventListener(eventName, (e) => {
      e.preventDefault();
      dropzone.classList.add('dragover');
    });
  });
  ['dragleave', 'drop'].forEach(eventName => {
    dropzone.addEventListener(eventName, (e) => {
      e.preventDefault();
      dropzone.classList.remove('dragover');
    });
  });
  dropzone.addEventListener('drop', (e) => {
    const files = e.dataTransfer.files;
    if (files && files.length > 0) {
      const file = files[0];
      const pathInput = document.getElementById('input-custom-rom-path');
      pathInput.value = file.path || file.name;
      runSafetyPrecheck();
    }
  });
}

document.getElementById('select-local-rom').addEventListener('change', runSafetyPrecheck);
document.getElementById('input-custom-rom-path').addEventListener('input', runSafetyPrecheck);

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
  rawLogEntries = [];
  document.getElementById('terminal-body').innerHTML = '<div class="log-line log-INFO">[00:00:00] [INFO] Logs cleared.</div>';
});

// Initialization
window.addEventListener('DOMContentLoaded', () => {
  fetchStatus();
  loadLocalPackages();
  loadCuratedSources();
  initSSEStream();
  pollTimer = setInterval(fetchStatus, 3000);
});
