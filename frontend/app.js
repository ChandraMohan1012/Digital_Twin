// Auto-detect backend URL from current page host.
// Works for localhost dev, LAN, and production deployment.
// Override by setting window.WEARTWIN_API_URL before this script loads.
const BASE_API = window.WEARTWIN_API_URL ||
    `http://${window.location.hostname || '127.0.0.1'}:8000`;

let PATIENT_ID = "3f0f57a9-2c05-4e3a-97bf-d9bb6c24cbc2";
const OFFLINE_QUEUE_KEY = "digital_twin_offline_queue";

let isBackendOnline = true;
let offlineQueue = JSON.parse(localStorage.getItem(OFFLINE_QUEUE_KEY) || "[]");
let patientsList = [];

// ---------------------------------------------------------------
// Input Validation — Physiological Safe Ranges
// ---------------------------------------------------------------
const VITAL_RANGES = {
    hr:     { min: 30,  max: 200, label: "Heart Rate (bpm)" },
    spo2:   { min: 70,  max: 100, label: "SpO2 (%)" },
    temp:   { min: 34,  max: 42,  label: "Temperature (\u00b0C)" },
    bp_sys: { min: 60,  max: 220, label: "Systolic BP (mmHg)" },
    bp_dia: { min: 30,  max: 140, label: "Diastolic BP (mmHg)" },
    activity_level: { min: 0, max: 10, label: "Activity Level" }
};

function validateVitals(payload) {
    const errors = [];
    for (const [key, range] of Object.entries(VITAL_RANGES)) {
        const val = payload[key];
        if (val === undefined || isNaN(val)) {
            errors.push(`${range.label} is required.`);
        } else if (val < range.min || val > range.max) {
            errors.push(`${range.label}: ${val} is out of valid range (${range.min}\u2013${range.max}).`);
        }
    }
    if (!isNaN(payload.bp_dia) && !isNaN(payload.bp_sys) && payload.bp_dia >= payload.bp_sys) {
        errors.push("Diastolic BP must be less than Systolic BP.");
    }
    return errors; // empty = valid
}

// ---------------------------------------------------------------
// Non-blocking inline notification (replaces alert())
// ---------------------------------------------------------------
function showStatus(divId, message, type = 'info') {
    const el = document.getElementById(divId);
    if (!el) return;
    const colors = { success: '#10b981', error: '#ef4444', warning: '#f59e0b', info: '#60a5fa' };
    const icons  = { success: '\u2713', error: '\u2715', warning: '\u26a0\ufe0f', info: '\u2139\ufe0f' };
    el.innerHTML = `<span style="color:${colors[type] || colors.info}">${icons[type] || ''} ${message}</span>`;
    if (type === 'success') setTimeout(() => { if (el.innerHTML.includes(message)) el.innerHTML = ''; }, 5000);
}

// Health check and connection monitor
async function checkBackendHealth() {
    try {
        const res = await fetch(`${BASE_API}/health`, { signal: AbortSignal.timeout(2000) });
        if (res.ok) {
            setOnlineStatus(true);
            if (offlineQueue.length > 0) {
                await flushOfflineQueue();
            }
        } else {
            setOnlineStatus(false);
        }
    } catch (err) {
        setOnlineStatus(false);
    }
}

function setOnlineStatus(online) {
    isBackendOnline = online;
    const dot = document.getElementById("statusDot");
    const text = document.getElementById("statusText");
    const indicator = document.getElementById("statusIndicator");

    if (online) {
        if (dot) {
            dot.className = "dot pulse";
            dot.style.backgroundColor = "#10b981";
        }
        if (text) text.innerText = offlineQueue.length > 0 ? `🟢 Online (Syncing ${offlineQueue.length}...)` : "🟢 Online & Synced";
        if (indicator) indicator.style.borderColor = "rgba(16, 185, 129, 0.3)";
    } else {
        if (dot) {
            dot.className = "dot pulse";
            dot.style.backgroundColor = "#f59e0b";
        }
        if (text) text.innerText = `⚡ Offline Edge Mode (Queued: ${offlineQueue.length})`;
        if (indicator) indicator.style.borderColor = "rgba(245, 158, 11, 0.4)";
    }
}

// Queue offline sensor event locally
function queueOfflineReading(payload) {
    offlineQueue.push(payload);
    localStorage.setItem(OFFLINE_QUEUE_KEY, JSON.stringify(offlineQueue));
    setOnlineStatus(false);

    // Compute local edge threshold risk when offline so UI stays alive!
    const actLvl = payload.activity_level ?? 5.0;
    const isHighRisk = payload.hr > 120 || payload.hr < 50 || payload.spo2 < 92 ||
                       payload.temp > 38.5 || actLvl < 2.0;
    const localState = {
        patient_id: payload.patient_id,
        status: "offline_edge",
        risk_label: isHighRisk ? "high" : "low",
        risk_confidence: isHighRisk ? 0.88 : 0.12,
        latest_hr: payload.hr,
        latest_spo2: payload.spo2,
        latest_temp: payload.temp,
        latest_bp_systolic: payload.bp_sys,
        latest_bp_diastolic: payload.bp_dia,
        rolling_avg_24h: { hr: payload.hr, spo2: payload.spo2, temp: payload.temp },
        updated_at: new Date().toISOString()
    };

    updateDashboard(localState);
}

// Flush offline queue when backend is restored
async function flushOfflineQueue() {
    if (offlineQueue.length === 0) return;
    
    console.log(`Syncing ${offlineQueue.length} offline telemetry events to backend...`);
    const statusDiv = document.getElementById("simulatorStatus");
    if (statusDiv) {
        statusDiv.innerHTML = `<span style="color: #f59e0b;">⚡ Auto-Syncing ${offlineQueue.length} offline queued events to cloud...</span>`;
    }

    try {
        const res = await fetch(`${BASE_API}/ingest/batch`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            // Each queued item already contains patient_id — do not duplicate at root
            body: JSON.stringify({ events: offlineQueue })
        });

        if (res.ok) {
            console.log("Offline queue flushed successfully!");
            offlineQueue = [];
            localStorage.removeItem(OFFLINE_QUEUE_KEY);
            setOnlineStatus(true);
            if (statusDiv) {
                statusDiv.innerHTML = `<span style="color: #10b981;">✓ All offline events synced to backend! Twin state updated.</span>`;
            }
            fetchTwinState();
        }
    } catch (err) {
        console.error("Batch sync failed, will retry:", err);
    }
}

async function fetchTwinState() {
    try {
        const response = await fetch(`${BASE_API}/twin/${PATIENT_ID}`);
        if (!response.ok) throw new Error("Network response was not ok");
        const data = await response.json();
        setOnlineStatus(true);
        updateDashboard(data);
    } catch (error) {
        setOnlineStatus(false);
        console.warn("Backend API offline. Operating in Local Edge Mode.");
    }
}

function updateDashboard(data) {
    // Risk Card
    const riskLabel = document.getElementById("riskLabel");
    const riskConf = document.getElementById("riskConf");

    if (riskLabel && data.risk_label !== riskLabel.innerText.toLowerCase()) {
        riskLabel.innerText = data.risk_label;
        riskLabel.className = data.risk_label === "high" ? "risk-high" : "risk-low";
    }
    if (riskConf) riskConf.innerText = `Confidence: ${(data.risk_confidence * 100).toFixed(0)}%`;

    // Patient Info
    const patientNameEl = document.getElementById("patientName");
    const currentPatientObj = patientsList.find(p => p.id === data.patient_id) || {};
    if (patientNameEl) patientNameEl.innerText = currentPatientObj.full_name || data.full_name || "Sample Patient";

    document.getElementById("patientId").innerText = data.patient_id || PATIENT_ID;
    const notesEl = document.getElementById("patientNotes");
    if (notesEl) notesEl.innerText = currentPatientObj.medical_notes || "Routine monitoring";
    document.getElementById("patientStatus").innerText = (data.status || "ACTIVE").toUpperCase();
    document.getElementById("lastUpdated").innerText = new Date(data.updated_at).toLocaleTimeString();

    // Vitals
    updateValue("valHR", data.latest_hr);
    updateValue("valSpO2", data.latest_spo2);
    updateValue("valTemp", data.latest_temp);
    updateValue("valBP", `${data.latest_bp_systolic || '--'}/${data.latest_bp_diastolic || '--'}`);

    // Update Real-Time Visual Chart
    updateChart(data.latest_hr, data.latest_spo2, data.latest_temp, data.updated_at);

    if (data.rolling_avg_24h) {
        if (data.rolling_avg_24h.hr) document.getElementById("avgHR").innerText = data.rolling_avg_24h.hr;
        if (data.rolling_avg_24h.spo2) document.getElementById("avgSpO2").innerText = data.rolling_avg_24h.spo2;
        if (data.rolling_avg_24h.temp) document.getElementById("avgTemp").innerText = data.rolling_avg_24h.temp;
    }

    // Alert Banner
    const alertBanner = document.getElementById("alertBanner");
    const alertMessage = document.getElementById("alertMessage");
    if (data.risk_label === "high") {
        alertBanner.classList.remove("hidden");
        alertMessage.innerText = `URGENT ALERT: Patient risk status escalated to HIGH! Immediate physiological evaluation advised.`;
    } else {
        alertBanner.classList.add("hidden");
    }
}

function updateValue(elementId, newValue) {
    const el = document.getElementById(elementId);
    if (el && el.innerText != newValue && newValue !== undefined && newValue !== null) {
        el.innerText = newValue;

        // Trigger flash animation
        const card = el.closest('.vital-card');
        if (card) {
            card.classList.remove("updated");
            void card.offsetWidth; // trigger reflow
            card.classList.add("updated");
        }
    }
}

// Render SHAP Explainability List
function renderShapList(shapData) {
    const shapList = document.getElementById("shapList");
    if (!shapData || Object.keys(shapData).length === 0) {
        shapList.innerHTML = `<p class="text-muted">Monitoring active. Live SHAP contributions will appear here.</p>`;
        return;
    }

    let html = '';
    const nameMap = {
        'hr': 'Heart Rate (HR)',
        'spo2': 'SpO2 Saturation',
        'temp': 'Body Temperature',
        'bp_sys': 'Systolic BP',
        'bp_dia': 'Diastolic BP',
        'activity_level': 'Activity Level (MPU6050)'
    };

    // Sort by absolute impact
    const sorted = Object.entries(shapData).sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]));

    for (const [key, val] of sorted) {
        const isPositive = val >= 0;
        const valClass = isPositive ? 'shap-positive' : 'shap-negative';
        const sign = isPositive ? '+' : '';
        const name = nameMap[key] || key.toUpperCase();

        html += `
            <div class="shap-item">
                <span class="shap-name">${name}</span>
                <span class="shap-val ${valClass}">${sign}${val.toFixed(3)} SHAP</span>
            </div>
        `;
    }
    shapList.innerHTML = html;
}

// Telemetry Ingestion Simulator Controls
document.getElementById("btnPresetNormal").addEventListener("click", (e) => {
    e.preventDefault();
    document.getElementById("inputHR").value = 75.0;
    document.getElementById("inputSpO2").value = 98.0;
    document.getElementById("inputTemp").value = 36.7;
    document.getElementById("inputBPSys").value = 118;
    document.getElementById("inputBPDia").value = 76;
    document.getElementById("inputActivity").value = 4.5;
    document.getElementById("activityVal").textContent = "4.5";
});

document.getElementById("btnPresetSpike").addEventListener("click", (e) => {
    e.preventDefault();
    document.getElementById("inputHR").value = 142.5;
    document.getElementById("inputSpO2").value = 88.0;
    document.getElementById("inputTemp").value = 39.2;
    document.getElementById("inputBPSys").value = 165;
    document.getElementById("inputBPDia").value = 102;
    document.getElementById("inputActivity").value = 1.0;
    document.getElementById("activityVal").textContent = "1.0";
});

// Live slider display
const actSlider = document.getElementById("inputActivity");
if (actSlider) {
    actSlider.addEventListener("input", () => {
        document.getElementById("activityVal").textContent = parseFloat(actSlider.value).toFixed(1);
    });
}

// Hardware Smart Band BLE Simulation Button Handler
const btnSimulateBLE = document.getElementById("btnSimulateBLE");
if (btnSimulateBLE) {
    btnSimulateBLE.addEventListener("click", async (e) => {
        e.preventDefault();
        const statusDiv = document.getElementById("simulatorStatus");
        statusDiv.innerHTML = `<span style="color: #8b5cf6;">⌚ Transmitting raw BLE packets from Hardware Band (ESP32-BAND-001)...</span>`;

        const blePayload = {
            device_id: "esp32-band-001",
            patient_id: PATIENT_ID,
            hr: parseFloat(document.getElementById("inputHR").value),
            spo2: parseFloat(document.getElementById("inputSpO2").value),
            temp: parseFloat(document.getElementById("inputTemp").value),
            bp_sys: parseInt(document.getElementById("inputBPSys").value),
            bp_dia: parseInt(document.getElementById("inputBPDia").value),
            activity_level: parseFloat(document.getElementById("inputActivity").value),
            battery_level: 95
        };

        if (!isBackendOnline) {
            queueOfflineReading(blePayload);
            statusDiv.innerHTML = `<span style="color: #f59e0b;">⚡ BLE Hardware Telemetry Queued Offline! Will auto-sync when online.</span>`;
            return;
        }

        try {
            const res = await fetch(`${BASE_API}/ingest/ble`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(blePayload)
            });

            if (!res.ok) throw new Error("BLE Hardware Ingestion Error");

            const data = await res.json();
            const batteryNote = data.ble_metadata ? ` | Battery: ${data.ble_metadata.battery_level}%` : '';
            if (data.risk_prediction && data.risk_prediction.label) {
                statusDiv.innerHTML = `<span style="color: #10b981;">⌚ Hardware BLE Packet Received!${batteryNote} | Risk: <strong>${data.risk_prediction.label.toUpperCase()}</strong></span>`;
                if (data.risk_prediction.top_risk_factors) {
                    renderShapList(data.risk_prediction.top_risk_factors);
                }
            } else {
                statusDiv.innerHTML = `<span style="color: #10b981;">⌚ Hardware BLE Packet Queued!${batteryNote} | Processing via Async Task Worker...</span>`;
            }
            fetchTwinState();
        } catch (err) {
            queueOfflineReading(blePayload);
            statusDiv.innerHTML = `<span style="color: #f59e0b;">⚡ Backend unreachable. Saved BLE Packet to local offline queue!</span>`;
        }
    });
}

document.getElementById("simulatorForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const statusDiv = document.getElementById("simulatorStatus");

    const payload = {
        patient_id: PATIENT_ID,
        hr: parseFloat(document.getElementById("inputHR").value),
        spo2: parseFloat(document.getElementById("inputSpO2").value),
        temp: parseFloat(document.getElementById("inputTemp").value),
        bp_sys: parseInt(document.getElementById("inputBPSys").value),
        bp_dia: parseInt(document.getElementById("inputBPDia").value),
        activity_level: parseFloat(document.getElementById("inputActivity").value)
    };

    // --- Input Validation ---
    const validationErrors = validateVitals(payload);
    if (validationErrors.length > 0) {
        showStatus("simulatorStatus", validationErrors[0], 'error');
        return;
    }

    showStatus("simulatorStatus", "Injecting sensor telemetry data...", 'info');

    if (!isBackendOnline) {
        queueOfflineReading(payload);
        showStatus("simulatorStatus", `Backend Offline. Telemetry saved to local queue (${offlineQueue.length} queued).`, 'warning');
        return;
    }

    try {
        const res = await fetch(`${BASE_API}/ingest`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });

        if (!res.ok) {
            const errData = await res.json();
            throw new Error(errData.detail || "Ingestion error");
        }

        const data = await res.json();
        if (data.risk_prediction && data.risk_prediction.label) {
            const anomalyNote = data.anomalies_detected > 0 ? ` | ${data.anomalies_detected} anomaly flag(s): ${data.anomaly_types.join(', ')}` : '';
            showStatus("simulatorStatus",
                `Telemetry Ingested! Risk: ${data.risk_prediction.label.toUpperCase()} (${(data.risk_prediction.confidence * 100).toFixed(0)}%)${anomalyNote}`,
                'success');

            if (data.risk_prediction.top_risk_factors) {
                renderShapList(data.risk_prediction.top_risk_factors);
            }
        } else {
            showStatus("simulatorStatus",
                `Telemetry Ingested & Queued for Async Processing (Event: ${data.event_id || 'OK'}). Updating twin via WebSocket...`,
                'success');
        }

        fetchTwinState();
    } catch (err) {
        queueOfflineReading(payload);
        showStatus("simulatorStatus", "Connection lost. Telemetry stored in local offline queue.", 'warning');
    }
});

// --- Chart.js Real-Time Telemetry Setup ---
let vitalsChart = null;
const maxChartPoints = 15;

function initChart() {
    const canvas = document.getElementById("vitalsChart");
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    
    vitalsChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: [],
            datasets: [
                {
                    label: 'Heart Rate (bpm)',
                    data: [],
                    borderColor: '#ef4444',
                    backgroundColor: 'rgba(239, 68, 68, 0.1)',
                    borderWidth: 2.5,
                    pointRadius: 4,
                    pointBackgroundColor: '#ef4444',
                    tension: 0.3,
                    fill: true,
                    yAxisID: 'yHR'
                },
                {
                    label: 'SpO2 (%)',
                    data: [],
                    borderColor: '#3b82f6',
                    backgroundColor: 'rgba(59, 130, 246, 0.08)',
                    borderWidth: 2.5,
                    pointRadius: 4,
                    pointBackgroundColor: '#3b82f6',
                    tension: 0.3,
                    fill: true,
                    yAxisID: 'ySpO2'
                },
                {
                    label: 'Temperature (°C)',
                    data: [],
                    borderColor: '#f59e0b',
                    backgroundColor: 'rgba(245, 158, 11, 0.05)',
                    borderWidth: 2,
                    pointRadius: 3,
                    pointBackgroundColor: '#f59e0b',
                    tension: 0.3,
                    fill: false,
                    yAxisID: 'yTemp'
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: { duration: 400 },
            plugins: {
                legend: { display: false },
                tooltip: {
                    backgroundColor: 'rgba(11, 15, 25, 0.9)',
                    titleColor: '#ffffff',
                    bodyColor: '#94a3b8',
                    borderColor: 'rgba(255, 255, 255, 0.1)',
                    borderWidth: 1,
                    mode: 'index',
                    intersect: false
                }
            },
            scales: {
                x: {
                    grid: { color: 'rgba(255, 255, 255, 0.05)' },
                    ticks: { color: '#94a3b8', font: { family: 'Inter', size: 11 } }
                },
                yHR: {
                    type: 'linear',
                    display: true,
                    position: 'left',
                    min: 40,
                    max: 180,
                    grid: { color: 'rgba(255, 255, 255, 0.05)' },
                    ticks: { color: '#ef4444', font: { family: 'Inter', size: 11 } }
                },
                ySpO2: {
                    type: 'linear',
                    display: false,
                    min: 70,
                    max: 100
                },
                yTemp: {
                    type: 'linear',
                    display: false,
                    min: 34,
                    max: 42
                }
            }
        }
    });
}

function updateChart(hr, spo2, temp, timestampStr) {
    if (!vitalsChart || hr === undefined || spo2 === undefined || temp === undefined) return;
    
    const timeLabel = timestampStr ? new Date(timestampStr).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : new Date().toLocaleTimeString();

    const labels = vitalsChart.data.labels;
    if (labels.length > 0 && labels[labels.length - 1] === timeLabel) return;

    labels.push(timeLabel);
    vitalsChart.data.datasets[0].data.push(hr);
    vitalsChart.data.datasets[1].data.push(spo2);
    vitalsChart.data.datasets[2].data.push(temp);

    if (labels.length > maxChartPoints) {
        labels.shift();
        vitalsChart.data.datasets[0].data.shift();
        vitalsChart.data.datasets[1].data.shift();
        vitalsChart.data.datasets[2].data.shift();
    }

    vitalsChart.update();
}

// Listen to browser network events
window.addEventListener('online', () => {
    setOnlineStatus(true);
    flushOfflineQueue();
});
window.addEventListener('offline', () => {
    setOnlineStatus(false);
});

// WebSocket Real-time Telemetry Client
let socket = null;
const WS_BASE_API = BASE_API.replace(/^http/, "ws");

function initWebSocket() {
    if (socket) {
        socket.close();
    }

    const wsUrl = `${WS_BASE_API}/ws/twin/${PATIENT_ID}`;
    console.log(`[WebSocket] Connecting to ${wsUrl}...`);
    socket = new WebSocket(wsUrl);

    socket.onopen = () => {
        console.log("[WebSocket] Connected successfully!");
        setOnlineStatus(true);
        if (offlineQueue.length > 0) {
            flushOfflineQueue();
        }
    };

    socket.onmessage = (event) => {
        try {
            const message = JSON.parse(event.data);
            if (message.event === "initial_state" && message.data) {
                updateDashboard(message.data);
            } else if (message.event === "twin_update") {
                if (message.current_twin_state) {
                    updateDashboard(message.current_twin_state);
                }
                if (message.risk_prediction && message.risk_prediction.top_risk_factors) {
                    renderShapList(message.risk_prediction.top_risk_factors);
                }
            }
        } catch (err) {
            console.error("[WebSocket] Message parsing error:", err);
        }
    };

    socket.onclose = () => {
        console.warn("[WebSocket] Disconnected. Reconnecting in 3 seconds...");
        setOnlineStatus(false);
        setTimeout(initWebSocket, 3000);
    };

    socket.onerror = (err) => {
        console.error("[WebSocket] Connection error:", err);
        socket.close();
    };
}

// Multi-Patient Management & Selector Logic
async function fetchPatientsList() {
    try {
        const res = await fetch(`${BASE_API}/patients`);
        if (res.ok) {
            const data = await res.json();
            patientsList = data.patients || [];
            renderPatientDropdown();
        }
    } catch (err) {
        console.error("Error fetching patients list:", err);
    }
}

function renderPatientDropdown() {
    const select = document.getElementById("patientSelect");
    if (!select) return;
    select.innerHTML = "";
    patientsList.forEach(p => {
        const opt = document.createElement("option");
        opt.value = p.id;
        opt.innerText = `${p.full_name} (${p.device_id || 'ID: ' + p.id.slice(0, 8)})`;
        if (p.id === PATIENT_ID) opt.selected = true;
        select.appendChild(opt);
    });
}

function switchPatient(newId) {
    if (!newId || newId === PATIENT_ID) return;
    console.log(`[PatientSwitch] Switching to Patient: ${newId}`);
    PATIENT_ID = newId;
    
    // Clear chart datasets for new patient
    if (vitalsChart) {
        vitalsChart.data.labels = [];
        vitalsChart.data.datasets.forEach(ds => ds.data = []);
        vitalsChart.update();
    }
    
    // Reconnect WebSocket to new patient channel & fetch state
    initWebSocket();
    fetchTwinState();
}

// Modal Event Listeners
document.addEventListener("DOMContentLoaded", () => {
    const patientSelect = document.getElementById("patientSelect");
    if (patientSelect) {
        patientSelect.addEventListener("change", (e) => switchPatient(e.target.value));
    }

    const btnNewPatient = document.getElementById("btnNewPatient");
    const btnCancelPatient = document.getElementById("btnCancelPatient");
    const patientModal = document.getElementById("patientModal");
    const registerForm = document.getElementById("registerPatientForm");

    if (btnNewPatient) {
        btnNewPatient.addEventListener("click", () => {
            if (patientModal) patientModal.classList.remove("hidden");
        });
    }

    if (btnCancelPatient) {
        btnCancelPatient.addEventListener("click", () => {
            if (patientModal) patientModal.classList.add("hidden");
        });
    }

    if (registerForm) {
        registerForm.addEventListener("submit", async (e) => {
            e.preventDefault();
            const name = document.getElementById("regName").value;
            const age = parseInt(document.getElementById("regAge").value, 10);
            const gender = document.getElementById("regGender").value;
            const bmi = parseFloat(document.getElementById("regBMI").value);
            const notes = document.getElementById("regNotes").value;

            try {
                const res = await fetch(`${BASE_API}/patients`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        full_name: name, age, gender, bmi, medical_notes: notes
                    })
                });

                if (res.ok) {
                    const data = await res.json();
                    // Non-blocking inline success — no alert()
                    const regStatus = document.getElementById("regStatus");
                    if (regStatus) { regStatus.innerHTML = `<span style="color:#10b981">\u2713 Patient "${name}" registered!</span>`; }
                    setTimeout(() => {
                        if (patientModal) patientModal.classList.add("hidden");
                    }, 1200);
                    await fetchPatientsList();
                    if (data.patient && data.patient.id) switchPatient(data.patient.id);
                } else {
                    const err = await res.json();
                    const regStatus = document.getElementById("regStatus");
                    if (regStatus) regStatus.innerHTML = `<span style="color:#ef4444">\u2715 ${err.detail || 'Registration failed.'}</span>`;
                }
            } catch (err) {
                console.error("Error registering patient:", err);
                const regStatus = document.getElementById("regStatus");
                if (regStatus) regStatus.innerHTML = `<span style="color:#ef4444">\u2715 Network error. Is the backend running?</span>`;
            }
        });
    }
});

// Initial setup
initChart();
checkBackendHealth();
fetchPatientsList();
initWebSocket();

// Periodic background health check (every 15s)
setInterval(() => {
    checkBackendHealth();
}, 15000);
