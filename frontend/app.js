const API_URL = "http://127.0.0.1:8000/twin/3f0f57a9-2c05-4e3a-97bf-d9bb6c24cbc2";

async function fetchTwinState() {
    try {
        const response = await fetch(API_URL);
        if (!response.ok) throw new Error("Network response was not ok");
        const data = await response.json();
        updateDashboard(data);
    } catch (error) {
        console.error("Failed to fetch Twin state:", error);
    }
}

function updateDashboard(data) {
    // Risk Card
    const riskLabel = document.getElementById("riskLabel");
    const riskConf = document.getElementById("riskConf");
    
    if(data.risk_label !== riskLabel.innerText.toLowerCase()) {
        riskLabel.innerText = data.risk_label;
        riskLabel.className = data.risk_label === "high" ? "risk-high" : "risk-low";
    }
    riskConf.innerText = `Confidence: ${(data.risk_confidence * 100).toFixed(0)}%`;

    // Patient Info
    document.getElementById("patientStatus").innerText = data.status.toUpperCase();
    document.getElementById("lastUpdated").innerText = new Date(data.updated_at).toLocaleTimeString();

    // Vitals
    updateValue("valHR", data.latest_hr);
    updateValue("valSpO2", data.latest_spo2);
    updateValue("valTemp", data.latest_temp);
    updateValue("valBP", `${data.latest_bp_systolic}/${data.latest_bp_diastolic}`);

    if (data.rolling_avg_24h) {
        if(data.rolling_avg_24h.hr) document.getElementById("avgHR").innerText = data.rolling_avg_24h.hr;
        if(data.rolling_avg_24h.spo2) document.getElementById("avgSpO2").innerText = data.rolling_avg_24h.spo2;
        if(data.rolling_avg_24h.temp) document.getElementById("avgTemp").innerText = data.rolling_avg_24h.temp;
    }
}

function updateValue(elementId, newValue) {
    const el = document.getElementById(elementId);
    if (el && el.innerText != newValue && newValue !== undefined && newValue !== null) {
        el.innerText = newValue;
        
        // Trigger flash animation
        const card = el.closest('.vital-card');
        if(card) {
            card.classList.remove("updated");
            void card.offsetWidth; // trigger reflow
            card.classList.add("updated");
        }
    }
}

// Initial fetch
fetchTwinState();
// Poll every 3 seconds
setInterval(fetchTwinState, 3000);
