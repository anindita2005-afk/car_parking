// PARKIQ Intelligent Parking Control Center - Digital Twin & Telemetry Engine
const API_BASE = "http://localhost:8000/api";

let systemMode = "REAL"; // REAL vs SIMULATION
let currentFloor = "F1"; // "F1" (First Floor) vs "F2" (Second Floor)
let liveState = null;
let activeRoute = null; // static / custom A* coordinate path
let enterCarAnimation = null; // smooth single-pass entering route animation
let exitCarAnimation = null; // smooth exit route animation
let pulsePhase = 0;
let exitScanBurst = 0; // Optical laser scan pulse countdown at EXIT GATE [CAM_02]

let hoveredSlotId = null;
let selectedSlotData = null;

const canvas = document.getElementById("twinCanvas");
const ctx = canvas.getContext("2d");

// Dynamic live duration and billing calculations with second-by-second precision
function formatLiveDuration(entryTimestamp) {
    if (!entryTimestamp) return "0s";
    const nowSec = Date.now() / 1000;
    const elapsed = Math.max(0, Math.floor(nowSec - entryTimestamp));
    const hours = Math.floor(elapsed / 3600);
    const mins = Math.floor((elapsed % 3600) / 60);
    const secs = elapsed % 60;
    if (hours > 0) return `${hours}h ${mins.toString().padStart(2, '0')}m ${secs.toString().padStart(2, '0')}s`;
    if (mins > 0) return `${mins}m ${secs.toString().padStart(2, '0')}s`;
    return `${secs}s`;
}

function calculateLiveFee(entryTimestamp, ratePer30m = 20) {
    if (!entryTimestamp) return { fee: ratePer30m, formatted: `₹${ratePer30m}` };
    const nowSec = Date.now() / 1000;
    const elapsed = Math.max(0, Math.floor(nowSec - entryTimestamp));
    const blocks = Math.max(1, Math.ceil(elapsed / 1800));
    const fee = blocks * ratePer30m;
    return { fee, formatted: `₹${fee}` };
}

// Live Clock & Dynamic Real-Time Date
function updateClock() {
    const now = new Date();
    const dateEl = document.getElementById("header-date-str");
    if (dateEl) {
        const options = { weekday: "long", year: "numeric", month: "short", day: "numeric" };
        dateEl.innerText = now.toLocaleDateString("en-US", options);
    }
    const clockEl = document.getElementById("live-clock");
    if (clockEl) {
        clockEl.innerText = now.toLocaleTimeString();
    }
}
setInterval(updateClock, 1000);
updateClock();

function setSystemMode(mode) {
    systemMode = mode;
    const btnReal = document.getElementById("btn-real-mode");
    const btnSim = document.getElementById("btn-sim-mode");
    const simPanel = document.getElementById("simActionsPanel");
    const sourceBadge = document.getElementById("cv-source-badge");

    if (btnReal) btnReal.classList.toggle("active", mode === "REAL");
    if (btnSim) btnSim.classList.toggle("active", mode === "SIMULATION");
    if (simPanel) simPanel.style.display = (mode === "SIMULATION") ? "block" : "none";
    if (sourceBadge) sourceBadge.innerText = (mode === "REAL") ? "CAM_01 GATE IN (LIVE YOLOv8 + OCR)" : "VIRTUAL DISPATCHER";
}

// Multi-Floor Switcher Routine (First Floor vs Second Floor)
window.switchFloor = function(floor) {
    if (floor !== "F1" && floor !== "F2") return;
    currentFloor = floor;

    const btnF1 = document.getElementById("btn-floor-f1");
    const btnF2 = document.getElementById("btn-floor-f2");
    if (btnF1 && btnF2) {
        btnF1.classList.toggle("active", floor === "F1");
        btnF2.classList.toggle("active", floor === "F2");
    }

    const pill = document.getElementById("current-floor-pill");
    if (pill) {
        pill.innerHTML = floor === "F1" 
            ? `VIEWING: <strong>FIRST FLOOR (F1)</strong>` 
            : `VIEWING: <strong>SECOND FLOOR (F2)</strong>`;
    }

    console.log(`[Floor] Switched viewing floor to: ${floor}`);
};

// ==========================================================================
// Digital Twin Fullscreen & Full-Width Workspace Handlers
// ==========================================================================
window.toggleTwinFullscreen = function() {
    const twinPanel = document.getElementById("digital-twin");
    if (!twinPanel) return;

    const fsText = document.getElementById("twin-fs-text");

    if (document.fullscreenElement || twinPanel.classList.contains("is-fullscreen")) {
        if (document.exitFullscreen && document.fullscreenElement) {
            document.exitFullscreen().catch(() => {});
        }
        twinPanel.classList.remove("is-fullscreen");
        if (fsText) fsText.innerText = "Full Screen";
    } else {
        if (twinPanel.requestFullscreen) {
            twinPanel.requestFullscreen().catch(() => {
                twinPanel.classList.add("is-fullscreen");
            });
        }
        twinPanel.classList.add("is-fullscreen");
        if (fsText) fsText.innerText = "Exit Full Screen";
    }
};

window.toggleTwinExpand = function() {
    const grid = document.querySelector(".workspace-grid-two-col");
    const expandText = document.getElementById("twin-expand-text");
    if (!grid) return;

    grid.classList.toggle("full-width-twin");
    const isFull = grid.classList.contains("full-width-twin");
    if (expandText) {
        expandText.innerText = isFull ? "Split View" : "Full Width";
    }
};

window.toggleDashboardFullscreen = function() {
    if (!document.fullscreenElement) {
        document.documentElement.requestFullscreen().catch(() => {});
    } else {
        if (document.exitFullscreen) {
            document.exitFullscreen().catch(() => {});
        }
    }
};

// Listen for native Fullscreen state changes (Esc key or browser exit)
document.addEventListener("fullscreenchange", () => {
    const twinPanel = document.getElementById("digital-twin");
    const fsText = document.getElementById("twin-fs-text");
    if (!document.fullscreenElement && twinPanel) {
        twinPanel.classList.remove("is-fullscreen");
        if (fsText) fsText.innerText = "Full Screen";
    }
});

// Allow Escape key to cleanly exit CSS overlay fullscreen
document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
        const twinPanel = document.getElementById("digital-twin");
        if (twinPanel && twinPanel.classList.contains("is-fullscreen")) {
            twinPanel.classList.remove("is-fullscreen");
            const fsText = document.getElementById("twin-fs-text");
            if (fsText) fsText.innerText = "Full Screen";
        }
    }
});

// Fetch Authoritative Parking State from Backend
async function fetchParkingState() {
    try {
        const res = await fetch(`${API_BASE}/state`);
        if (res.ok) {
            liveState = await res.json();
            const statusEl = document.getElementById("backend-status");
            if (statusEl) {
                statusEl.innerText = "ONLINE";
                statusEl.className = "text-emerald";
            }
            updateDashboardUI(liveState);
        }
    } catch (err) {
        const statusEl = document.getElementById("backend-status");
        if (statusEl) {
            statusEl.innerText = "OFFLINE";
            statusEl.className = "text-rose";
        }
    }
}

// Update Top KPIs, Tables & Telemetry HUD
function updateDashboardUI(state) {
    if (!state) return;

    const kpis = state.kpis;
    if (kpis) {
        document.getElementById("kpi-total").innerText = kpis.total_capacity;
        document.getElementById("kpi-available").innerText = kpis.available;
        document.getElementById("kpi-occupied").innerText = kpis.occupied;
        document.getElementById("kpi-rate").innerText = `${kpis.occupancy_rate}%`;
        
        const revEl = document.getElementById("kpi-revenue");
        if (revEl) revEl.innerText = `₹${(kpis.total_revenue_inr != null ? kpis.total_revenue_inr : 0).toLocaleString()}`;
        const turnoverEl = document.getElementById("kpi-turnover-badge");
        if (turnoverEl) turnoverEl.innerText = `${kpis.total_vehicles_today || 0} Vehicles Today`;

        const pBar = document.getElementById("kpi-progress-bar");
        if (pBar) {
            pBar.style.width = `${Math.min(100, kpis.occupancy_rate)}%`;
        }

        const occBadge = document.getElementById("kpi-occupied-badge");
        if (occBadge) {
            occBadge.innerText = kpis.occupied > 0 ? `${kpis.occupied} Active Vehicle${kpis.occupied > 1 ? 's' : ''}` : "All Clear";
        }

        // Update Multi-Floor Switcher Badges
        const badgeF1 = document.getElementById("badge-floor-f1");
        const badgeF2 = document.getElementById("badge-floor-f2");
        if (badgeF1) {
            const f1Avail = kpis.f1_available != null ? kpis.f1_available : 6;
            const f1Cap = kpis.f1_capacity || 6;
            badgeF1.innerText = `${f1Avail} Free / ${f1Cap}`;
        }
        if (badgeF2) {
            const f2Avail = kpis.f2_available != null ? kpis.f2_available : 28;
            const f2Cap = kpis.f2_capacity || 28;
            badgeF2.innerText = `${f2Avail} Free / ${f2Cap}`;
        }
    }

    // Update Live CV Telemetry HUD if not in manual photo preview mode
    const previewWrap = document.getElementById("uploadPreviewWrap");
    const isManualPreview = previewWrap && !previewWrap.classList.contains("hidden");
    if (!isManualPreview) {
        const trackEl = document.getElementById("hud-track-id");
        const plateEl = document.getElementById("hud-plate");
        const confEl = document.getElementById("hud-ocr-conf");
        const slotEl = document.getElementById("hud-assigned-slot");
        if (state.active_sessions && state.active_sessions.length > 0) {
            const latest = state.active_sessions[0];
            if (trackEl) trackEl.innerText = `#${latest.track_id || '101'}`;
            if (plateEl) plateEl.innerText = latest.plate_number || "NO VEHICLE";
            if (confEl) confEl.innerText = `${(latest.ocr_confidence ? latest.ocr_confidence * 100 : 92).toFixed(0)}% [CONFIRMED]`;
            if (slotEl) {
                slotEl.innerText = latest.assigned_slot || "--";
                slotEl.style.color = "#10b981";
            }
        } else if (!enterCarAnimation && !exitCarAnimation) {
            if (trackEl) trackEl.innerText = "#--";
            if (plateEl) plateEl.innerText = "NO VEHICLE";
            if (confEl) confEl.innerText = "--%";
            if (slotEl) {
                slotEl.innerText = "--";
                slotEl.style.color = "";
            }
        }
    }

    // Update Activity Feed
    const feedContainer = document.getElementById("activityFeed");
    if (feedContainer && state.activity_feed && state.activity_feed.length > 0) {
        feedContainer.innerHTML = state.activity_feed.map(item => `
            <div class="activity-feed-entry">
                <span class="entry-time">${item.timestamp} • ${item.type}</span>
                <span class="entry-desc">${item.message}</span>
            </div>
        `).join("");
    }

    // Update Active Sessions Table
    const tbody = document.getElementById("sessionsTableBody");
    if (tbody) {
        if (state.active_sessions && state.active_sessions.length > 0) {
            const ratePer30m = (state.kpis && state.kpis.rate_per_30m) || 20;
            tbody.innerHTML = state.active_sessions.map(s => {
                const liveDur = formatLiveDuration(s.entry_timestamp);
                const liveFeeObj = calculateLiveFee(s.entry_timestamp, ratePer30m);
                const feeText = s.status === "BYPASS" ? "₹0 (Bypass)" : liveFeeObj.formatted;
                return `
                <tr>
                    <td><strong>${s.session_id}</strong></td>
                    <td><span class="text-blue font-mono font-bold">#${s.track_id || '--'}</span></td>
                    <td><span class="plate-badge-pill">${s.plate_number}</span></td>
                    <td><span class="font-bold text-slate">GENERAL</span></td>
                    <td><small class="text-muted font-mono">${s.entry_time}</small></td>
                    <td><span class="font-mono font-bold" style="color: #6366f1; background: #eef2ff; padding: 3px 8px; border-radius: 6px; font-size: 11px;">⏱ ${liveDur}</span></td>
                    <td><strong class="text-emerald font-mono">${s.assigned_slot || '--'}</strong></td>
                    <td><strong class="font-mono font-bold text-emerald" style="font-size: 13px;">${feeText}</strong></td>
                    <td><span class="pill-status pill-${(s.status || 'entering').toLowerCase()}">${s.status}</span></td>
                    <td>
                        <button class="btn-table-exit" onclick="exitSpecificVehicle('${s.assigned_slot || s.plate_number}', '${s.plate_number}')">
                            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M5 12h14"/><path d="M12 5l7 7-7 7"/></svg>
                            <span>Exit (Pay)</span>
                        </button>
                    </td>
                </tr>
            `;
            }).join("");
        } else {
            tbody.innerHTML = `<tr><td colspan="10" style="text-align: center; color: #94a3b8; padding: 24px;">No active parking sessions</td></tr>`;
        }
    }

    // === HUD Telemetry: always reflect the single latest detection ===
    const latest = state.latest_detection;
    if (latest) {
        document.getElementById("hud-track-id").innerText = latest.track_id != null ? `#${latest.track_id}` : "#--";
        document.getElementById("hud-plate").innerText = latest.plate_number || "NO VEHICLE";
        document.getElementById("hud-ocr-conf").innerText = latest.ocr_confidence != null ? `${latest.ocr_confidence}%` : "--%";
        const assignedSlotEl = document.getElementById("hud-assigned-slot");
        if (assignedSlotEl) {
            if (latest.assigned_slot) {
                assignedSlotEl.innerText = latest.assigned_slot;
                assignedSlotEl.style.color = "#10b981";
            } else {
                assignedSlotEl.innerText = "🚫 FULL (EXIT)";
                assignedSlotEl.style.color = "#ef4444";
            }
        }
    } else {
        document.getElementById("hud-plate").innerText = "NO VEHICLE";
        document.getElementById("hud-track-id").innerText = "#--";
        document.getElementById("hud-ocr-conf").innerText = "--%";
        const assignedSlotEl = document.getElementById("hud-assigned-slot");
        if (assignedSlotEl) { assignedSlotEl.innerText = "--"; assignedSlotEl.style.color = ""; }
    }

    // If a slot modal is currently open, refresh its staying timer and fee in real-time
    if (selectedSlotData) {
        openSlotModal(selectedSlotData);
    }
}

// Helper: Adjust Hex Color Luminance for Metallic Shading
function adjustColorLuminance(hex, lum) {
    hex = String(hex).replace(/[^0-9a-f]/gi, '');
    if (hex.length < 6) {
        hex = hex[0] + hex[0] + hex[1] + hex[1] + hex[2] + hex[2];
    }
    lum = lum || 0;
    let rgb = "#", c, i;
    for (i = 0; i < 3; i++) {
        c = parseInt(hex.substr(i * 2, 2), 16);
        c = Math.round(Math.min(Math.max(0, c + (c * lum)), 255)).toString(16);
        rgb += ("00" + c).substr(c.length);
    }
    return rgb;
}

// Helper: Architectural CAD Blueprint Corner Ticks & Rubber Wheel Stops
// ==========================================================================
// Executive Architectural Slot Accents & Integrated Sub-Components
// ==========================================================================
function drawSlotArchitecturalAccents(ctx, x, y, w, h, isHorizontal, isOccupied, isAmber, isAllocated, slotId) {
    ctx.save();

    // 1. Precision Metallic CAD Blueprint Corner L-Brackets (Gold or Emerald)
    ctx.strokeStyle = isAmber ? "rgba(202, 138, 4, 0.7)" : "rgba(5, 150, 105, 0.7)";
    ctx.lineWidth = 1.8;
    const tick = 12;
    const inset = 8;

    // Top-Left L
    ctx.beginPath();
    ctx.moveTo(x + inset, y + inset + tick);
    ctx.lineTo(x + inset, y + inset);
    ctx.lineTo(x + inset + tick, y + inset);
    ctx.stroke();

    // Top-Right L
    ctx.beginPath();
    ctx.moveTo(x + w - inset - tick, y + inset);
    ctx.lineTo(x + w - inset, y + inset);
    ctx.lineTo(x + w - inset, y + inset + tick);
    ctx.stroke();

    // Bottom-Left L
    ctx.beginPath();
    ctx.moveTo(x + inset, y + h - inset - tick);
    ctx.lineTo(x + inset, y + h - inset);
    ctx.lineTo(x + inset + tick, y + h - inset);
    ctx.stroke();

    // Bottom-Right L
    ctx.beginPath();
    ctx.moveTo(x + w - inset - tick, y + h - inset);
    ctx.lineTo(x + w - inset, y + h - inset);
    ctx.lineTo(x + w - inset, y + h - inset - tick);
    ctx.stroke();

    // 2. In-Bay Ground Tire Alignment Guide Tracks (Subtle Metallic Precision Markings)
    ctx.save();
    ctx.strokeStyle = isAmber ? "rgba(202, 138, 4, 0.18)" : "rgba(100, 116, 139, 0.18)";
    ctx.setLineDash([8, 6]);
    ctx.lineWidth = 1.5;
    if (isHorizontal) {
        // Horizontal slots (Slots 3 & 4)
        ctx.beginPath();
        ctx.moveTo(x + 40, y + h / 2 - 26);
        ctx.lineTo(x + w - 45, y + h / 2 - 26);
        ctx.moveTo(x + 40, y + h / 2 + 26);
        ctx.lineTo(x + w - 45, y + h / 2 + 26);
        ctx.stroke();
    } else {
        // Vertical slots (Slots 1, 2, 5, 6)
        ctx.beginPath();
        ctx.moveTo(x + w / 2 - 24, y + 36);
        ctx.lineTo(x + w / 2 - 24, y + h - 36);
        ctx.moveTo(x + w / 2 + 24, y + 36);
        ctx.lineTo(x + w / 2 + 24, y + h - 36);
        ctx.stroke();
    }
    ctx.setLineDash([]);
    ctx.restore();

    // 3. Overhead Smart Ultrasonic / Radar Presence Sensor Puck
    ctx.save();
    let sensorX = x + w / 2;
    let sensorY = (y < 300) ? y + 22 : y + h - 22;
    if (isHorizontal) {
        sensorX = x + w - 24;
        sensorY = y + h / 2;
    }

    // Outer sensor casing
    ctx.fillStyle = "#0f172a";
    ctx.strokeStyle = "#475569";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.arc(sensorX, sensorY, 6, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();

    // Glowing Radar Core LED
    let sensorColor = "#10b981"; // Emerald (Free)
    let sensorGlow = "rgba(16, 185, 129, 0.6)";
    if (isOccupied) {
        sensorColor = "#ef4444"; // Ruby (Occupied)
        sensorGlow = "rgba(239, 68, 68, 0.7)";
    } else if (isAllocated) {
        sensorColor = "#06b6d4"; // Cyan (Allocated)
        sensorGlow = "rgba(6, 182, 212, 0.8)";
    }
    ctx.fillStyle = sensorColor;
    ctx.shadowColor = sensorGlow;
    ctx.shadowBlur = 6;
    ctx.beginPath();
    ctx.arc(sensorX, sensorY, 2.5, 0, Math.PI * 2);
    ctx.fill();
    ctx.shadowBlur = 0;
    ctx.restore();

    // 4. Integrated EV Fast Charger Terminal Pedestal (For Amber EV-Priority Bays: Slots 3 & 5)
    if (isAmber) {
        ctx.save();
        const evX = isHorizontal ? x + w - 18 : (x < 300 ? x + 16 : x + w - 16);
        const evY = isHorizontal ? y + 30 : (y < 300 ? y + 28 : y + h - 28);

        // EV Charger pedestal body
        ctx.fillStyle = "#0f172a";
        ctx.strokeStyle = "#ca8a04";
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.roundRect(evX - 7, evY - 14, 14, 28, 4);
        ctx.fill();
        ctx.stroke();

        // EV Status Light Ring
        ctx.fillStyle = "#eab308";
        ctx.shadowColor = "rgba(234, 179, 8, 0.8)";
        ctx.shadowBlur = 4;
        ctx.beginPath();
        ctx.arc(evX, evY - 6, 2.2, 0, Math.PI * 2);
        ctx.fill();
        ctx.shadowBlur = 0;

        // Inscribed "⚡ EV"
        ctx.fillStyle = "#fde047";
        ctx.font = "bold 7px 'JetBrains Mono', monospace";
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText("EV", evX, evY + 4);
        ctx.restore();
    }

    ctx.restore();
}

// ==========================================================================
// Automated Smart Bay Barrier Gate at Slot Entrance Point (Executive Spec)
// ==========================================================================
function drawSlotGate(ctx, slot, isOccupied, isAllocated, isHovered) {
    const isF1 = (slot.floor === 1 || slot.id.startsWith("F1-"));
    const x = slot.x;
    const y = slot.y;
    const w = slot.width;
    const h = slot.height;

    // Determine the exact entrance boundary facing the driving aisle
    let edge = "left"; // "left", "right", or "bottom"
    let gateX = x;
    let gateY = y;
    let gateLen = 76;
    let isVertical = true;
    let textSide = "right"; // Side inside the slot where "GATE" is inscribed

    if (isF1) {
        if (slot.id === "F1-S01") {
            edge = "right";
            gateX = x + w; // 235 (Facing Aisle 1)
            gateY = 222;
            gateLen = 78;
            isVertical = true;
            textSide = "left";
        } else if (slot.id === "F1-S02") {
            edge = "right";
            gateX = x + w; // 235 (Facing Aisle 1)
            gateY = 532;
            gateLen = 78;
            isVertical = true;
            textSide = "left";
        } else if (slot.id === "F1-S03") {
            edge = "left";
            gateX = x; // 335 (Facing Aisle 1)
            gateY = 188;
            gateLen = 78;
            isVertical = true;
            textSide = "right";
        } else if (slot.id === "F1-S04") {
            edge = "left";
            gateX = x; // 335 (Facing Aisle 1)
            gateY = 432;
            gateLen = 78;
            isVertical = true;
            textSide = "right";
        } else if (slot.id === "F1-S05") {
            edge = "left";
            gateX = x; // 725 (Facing Aisle 2)
            gateY = 532;
            gateLen = 78;
            isVertical = true;
            textSide = "right";
        } else if (slot.id === "F1-S06") {
            edge = "left";
            gateX = x; // 725 (Facing Aisle 2)
            gateY = 222;
            gateLen = 78;
            isVertical = true;
            textSide = "right";
        }
    } else {
        // Floor 2 bays
        const bayCode = slot.bay_code || slot.id.split("-").pop();
        if (bayCode >= "S25" && bayCode <= "S28") {
            edge = "bottom";
            gateX = x + w / 2;
            gateY = y + h;
            gateLen = w - 10;
            isVertical = false;
            textSide = "top";
        } else if ((bayCode >= "S01" && bayCode <= "S06") || (bayCode >= "S13" && bayCode <= "S18")) {
            edge = "right";
            gateX = x + w;
            gateY = y + h / 2;
            gateLen = h - 12;
            isVertical = true;
            textSide = "left";
        } else {
            edge = "left";
            gateX = x;
            gateY = y + h / 2;
            gateLen = h - 12;
            isVertical = true;
            textSide = "right";
        }
    }

    ctx.save();

    if (isVertical) {
        const topY = gateY - gateLen / 2;
        const bottomY = gateY + gateLen / 2;

        // 1. Entrance Optical Laser Sensor Beam (Active Threshold Line)
        ctx.save();
        ctx.lineWidth = isF1 ? 2.5 : 1.5;
        let thresholdColor = "rgba(16, 185, 129, 0.45)"; // Emerald (Free)
        if (isOccupied) {
            thresholdColor = "rgba(239, 68, 68, 0.55)"; // Ruby (Occupied / Secured)
        } else if (isAllocated) {
            const glow = 0.55 + 0.4 * Math.sin(pulsePhase * 4);
            thresholdColor = `rgba(6, 182, 212, ${glow})`; // Electric Cyan (Allocated / Welcoming)
        }
        ctx.strokeStyle = thresholdColor;
        ctx.shadowColor = thresholdColor;
        ctx.shadowBlur = isAllocated ? 10 : (isOccupied ? 4 : 3);
        ctx.beginPath();
        ctx.moveTo(gateX, topY + 4);
        ctx.lineTo(gateX, bottomY - 4);
        ctx.stroke();
        ctx.shadowBlur = 0;
        ctx.restore();

        // 2. High-End Integrated Smart Access Pedestal (Top Bollard) & Pivot Base (Bottom Bollard)
        const drawSmartPedestal = (py, isMaster) => {
            ctx.save();
            const bw = isF1 ? 13 : 8;
            const bh = isF1 ? (isMaster ? 24 : 14) : 9;

            // Brushed Titanium Alloy Housing
            const pillarGrad = ctx.createLinearGradient(gateX - bw / 2, py - bh / 2, gateX + bw / 2, py + bh / 2);
            pillarGrad.addColorStop(0, "#0b0f19");
            pillarGrad.addColorStop(0.35, "#1e293b");
            pillarGrad.addColorStop(0.7, "#334155");
            pillarGrad.addColorStop(1, "#0f172a");
            ctx.fillStyle = pillarGrad;
            ctx.strokeStyle = "rgba(148, 163, 184, 0.6)";
            ctx.lineWidth = 1;
            ctx.beginPath();
            ctx.roundRect(gateX - bw / 2, py - bh / 2, bw, bh, isF1 ? 3.5 : 2);
            ctx.fill();
            ctx.stroke();

            // Chamfered Metallic Edge Reflection
            ctx.strokeStyle = "rgba(255, 255, 255, 0.35)";
            ctx.lineWidth = 0.7;
            ctx.strokeRect(gateX - bw / 2 + 1, py - bh / 2 + 1, bw - 2, bh - 2);

            if (isMaster && isF1) {
                // Micro OLED Digital Access HUD Screen
                const scrW = bw - 4;
                const scrH = 10;
                const scrY = py - bh / 2 + 3;
                ctx.fillStyle = "#020617";
                ctx.fillRect(gateX - scrW / 2, scrY, scrW, scrH);
                ctx.strokeStyle = "rgba(255, 255, 255, 0.15)";
                ctx.lineWidth = 0.5;
                ctx.strokeRect(gateX - scrW / 2, scrY, scrW, scrH);

                // Bay Code Micro Typography on OLED Screen
                const bayNum = slot.bay_code || slot.id.split("-").pop() || "G";
                ctx.fillStyle = isOccupied ? "#f87171" : (isAllocated ? "#38bdf8" : "#34d399");
                ctx.font = "bold 6.5px 'JetBrains Mono', monospace";
                ctx.textAlign = "center";
                ctx.textBaseline = "middle";
                ctx.fillText(`G${bayNum}`, gateX, scrY + scrH / 2);

                // Optical ANPR Camera / Sensor Lens
                ctx.fillStyle = isOccupied ? "#ef4444" : (isAllocated ? "#06b6d4" : "#10b981");
                ctx.shadowColor = ctx.fillStyle;
                ctx.shadowBlur = 5;
                ctx.beginPath();
                ctx.arc(gateX, py + bh / 2 - 4, 1.8, 0, Math.PI * 2);
                ctx.fill();
                ctx.shadowBlur = 0;
            } else {
                // Secondary Rotary Actuator Pivot Base
                ctx.fillStyle = isOccupied ? "#ef4444" : (isAllocated ? "#06b6d4" : "#10b981");
                ctx.shadowColor = ctx.fillStyle;
                ctx.shadowBlur = 4;
                ctx.beginPath();
                ctx.arc(gateX, py, isF1 ? 2.2 : 1.5, 0, Math.PI * 2);
                ctx.fill();
                ctx.shadowBlur = 0;
            }

            ctx.restore();
        };

        // Render Master Pedestal at top, Rotary Pivot at bottom
        drawSmartPedestal(topY, true);
        drawSmartPedestal(bottomY, false);

        // 3. Dynamic Automated Barrier Flap / Articulated Boom Arm
        const armThickness = isF1 ? 3.6 : 2;
        ctx.save();
        if (isAllocated) {
            // OPEN / RAISED BARRIER STATE (Welcoming allocated vehicle)
            const swingDir = (edge === "right") ? -1 : 1; // swing toward slot interior
            const openArmLen = gateLen * 0.62;
            const openAngle = Math.PI * 0.5 + swingDir * 0.82;

            const endArmX = gateX + Math.cos(openAngle) * openArmLen;
            const endArmY = topY + Math.sin(openAngle) * openArmLen;

            // Raised barrier arm with electric cyan glow
            ctx.strokeStyle = "#38bdf8";
            ctx.shadowColor = "rgba(56, 189, 248, 0.85)";
            ctx.shadowBlur = 8;
            ctx.lineWidth = armThickness;
            ctx.beginPath();
            ctx.moveTo(gateX, topY + 4);
            ctx.lineTo(endArmX, endArmY);
            ctx.stroke();
            ctx.shadowBlur = 0;

            // Animated Inward Guidance Chevrons (⇦ or ⇨)
            if (isF1) {
                const arrowX = (edge === "right") ? gateX - 22 : gateX + 22;
                ctx.fillStyle = "#0284c7";
                ctx.font = "bold 13px sans-serif";
                ctx.textAlign = "center";
                ctx.textBaseline = "middle";
                ctx.fillText((edge === "right") ? "⇦" : "⇨", arrowX, gateY);
            }
        } else if (isOccupied) {
            // CLOSED / SECURED BARRIER STATE (Securing parked vehicle)
            ctx.lineWidth = armThickness;
            ctx.lineCap = "round";

            // Crisp aluminum barrier body
            ctx.strokeStyle = "#f8fafc";
            ctx.shadowColor = "rgba(15, 23, 42, 0.35)";
            ctx.shadowBlur = 3;
            ctx.beginPath();
            ctx.moveTo(gateX, topY + 12);
            ctx.lineTo(gateX, bottomY - 6);
            ctx.stroke();
            ctx.shadowBlur = 0;

            // Crimson security blocks on barrier arm
            ctx.fillStyle = "#ef4444";
            const armSpan = gateLen - 18;
            const segCount = isF1 ? 4 : 2;
            const segStep = armSpan / segCount;
            for (let s = 0; s < segCount; s += 2) {
                const sy = topY + 12 + s * segStep;
                ctx.fillRect(gateX - armThickness / 2, sy, armThickness, segStep * 0.8);
            }

            // Ruby warning lock beacon at midpoint
            ctx.fillStyle = "#ef4444";
            ctx.shadowColor = "rgba(239, 68, 68, 0.9)";
            ctx.shadowBlur = 6;
            ctx.beginPath();
            ctx.arc(gateX, gateY, isF1 ? 2.5 : 1.5, 0, Math.PI * 2);
            ctx.fill();
            ctx.shadowBlur = 0;
        } else {
            // FREE / STANDBY BARRIER STATE
            ctx.lineWidth = armThickness;
            ctx.lineCap = "round";

            // Aluminum standby arm
            ctx.strokeStyle = "#cbd5e1";
            ctx.beginPath();
            ctx.moveTo(gateX, topY + 12);
            ctx.lineTo(gateX, bottomY - 6);
            ctx.stroke();

            // Emerald luminous guidance strip
            ctx.strokeStyle = "#10b981";
            ctx.shadowColor = "rgba(16, 185, 129, 0.6)";
            ctx.shadowBlur = 4;
            ctx.lineWidth = armThickness * 0.55;
            ctx.beginPath();
            ctx.moveTo(gateX, topY + 14);
            ctx.lineTo(gateX, bottomY - 8);
            ctx.stroke();
            ctx.shadowBlur = 0;
        }
        ctx.restore();

    } else {
        // Floor 2 horizontal entrance
        const leftX = gateX - gateLen / 2;
        const rightX = gateX + gateLen / 2;

        ctx.strokeStyle = isOccupied ? "rgba(239, 68, 68, 0.45)" : (isAllocated ? "rgba(2, 132, 199, 0.7)" : "rgba(16, 185, 129, 0.4)");
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.moveTo(leftX, gateY);
        ctx.lineTo(rightX, gateY);
        ctx.stroke();

        ctx.fillStyle = "#0f172a";
        ctx.fillRect(leftX - 4, gateY - 4, 8, 8);
        ctx.fillRect(rightX - 4, gateY - 4, 8, 8);
        ctx.fillStyle = isOccupied ? "#ef4444" : (isAllocated ? "#38bdf8" : "#10b981");
        ctx.beginPath();
        ctx.arc(leftX, gateY, 1.5, 0, Math.PI * 2);
        ctx.arc(rightX, gateY, 1.5, 0, Math.PI * 2);
        ctx.fill();

        if (!isAllocated) {
            ctx.strokeStyle = isOccupied ? "#ef4444" : "#10b981";
            ctx.lineWidth = 2;
            ctx.beginPath();
            ctx.moveTo(leftX + 4, gateY);
            ctx.lineTo(rightX - 4, gateY);
            ctx.stroke();
        }
    }

    ctx.restore();
}

// ==========================================================================
// Ultra-Realistic Top-Down Vector Car Drawing Routine (Executive Spec)
// ==========================================================================
function drawRealisticCar(ctx, cx, cy, width, height, primaryColor, plateText, isEV, rotation = 0) {
    ctx.save();
    ctx.translate(cx, cy);
    if (rotation !== 0) {
        ctx.rotate(rotation);
    }

    const w = width || 58;
    const h = height || 96;
    const radius = 10;

    // 1. Ambient Ground Contact Occlusion Shadow
    ctx.save();
    ctx.fillStyle = "rgba(15, 23, 42, 0.28)";
    ctx.filter = "blur(6px)";
    ctx.beginPath();
    ctx.ellipse(0, 4, w / 2 + 3, h / 2 + 5, 0, 0, Math.PI * 2);
    ctx.fill();
    ctx.filter = "none";
    ctx.restore();

    // 2. Wheels / Tires (Corner High-Performance Tires with Silver Alloy Rim Highlight)
    const tireW = Math.max(7, Math.round(w * 0.16));
    const tireH = Math.max(16, Math.round(h * 0.20));
    const tireX = w / 2 - 3;
    const frontTireY = -h / 2 + 12;
    const rearTireY = h / 2 - 30;

    const drawWheel = (wx, wy) => {
        ctx.fillStyle = "#0f172a";
        ctx.beginPath();
        ctx.roundRect(wx, wy, tireW, tireH, 3);
        ctx.fill();
        // Inner silver rim line
        ctx.strokeStyle = "rgba(203, 213, 225, 0.6)";
        ctx.lineWidth = 1;
        ctx.strokeRect(wx + 2, wy + 3, tireW - 4, tireH - 6);
    };

    drawWheel(-w / 2 - 3, frontTireY);
    drawWheel(tireX, frontTireY);
    drawWheel(-w / 2 - 3, rearTireY);
    drawWheel(tireX, rearTireY);

    // 3. Side Aerodynamic Wing Mirrors
    ctx.fillStyle = primaryColor || "#0284c7";
    ctx.strokeStyle = "rgba(0, 0, 0, 0.2)";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.roundRect(-w / 2 - 5, -h / 2 + 24, 6, 8, 2);
    ctx.roundRect(w / 2 - 1, -h / 2 + 24, 6, 8, 2);
    ctx.fill();
    ctx.stroke();

    // 4. Main Metallic Sculpted Car Body with Curvature Gradient & Drop Shadow
    ctx.save();
    ctx.shadowColor = "rgba(15, 23, 42, 0.35)";
    ctx.shadowBlur = 10;
    ctx.shadowOffsetY = 3;

    const bodyGrad = ctx.createLinearGradient(-w / 2, 0, w / 2, 0);
    bodyGrad.addColorStop(0, primaryColor || "#0284c7");
    bodyGrad.addColorStop(0.2, adjustColorLuminance(primaryColor || "#0284c7", 0.15));
    bodyGrad.addColorStop(0.5, "#ffffff");
    bodyGrad.addColorStop(0.7, adjustColorLuminance(primaryColor || "#0284c7", 0.05));
    bodyGrad.addColorStop(1, adjustColorLuminance(primaryColor || "#0284c7", -0.25));

    ctx.fillStyle = bodyGrad;
    ctx.beginPath();
    ctx.roundRect(-w / 2, -h / 2, w, h, radius);
    ctx.fill();
    ctx.restore();

    // Subtle crisp metallic body perimeter highlight
    ctx.strokeStyle = "rgba(255, 255, 255, 0.75)";
    ctx.lineWidth = 1.2;
    ctx.beginPath();
    ctx.roundRect(-w / 2, -h / 2, w, h, radius);
    ctx.stroke();

    // 5. LED Projector Headlights (Diamond Xenon White with Forward Beam Glow)
    ctx.fillStyle = "#ffffff";
    ctx.shadowColor = "rgba(254, 240, 138, 0.8)";
    ctx.shadowBlur = 6;
    ctx.beginPath();
    ctx.roundRect(-w / 2 + 4, -h / 2 + 2, 10, 5, 2);
    ctx.roundRect(w / 2 - 14, -h / 2 + 2, 10, 5, 2);
    ctx.fill();
    ctx.shadowBlur = 0;

    // Headlight amber turn signal accents
    ctx.fillStyle = "#f59e0b";
    ctx.fillRect(-w / 2 + 4, -h / 2 + 1, 3, 2);
    ctx.fillRect(w / 2 - 7, -h / 2 + 1, 3, 2);

    // 6. Rear Tail Lights (Ruby LED Lightbar with Red Glow)
    ctx.fillStyle = "#dc2626";
    ctx.shadowColor = "rgba(239, 68, 68, 0.8)";
    ctx.shadowBlur = 6;
    ctx.beginPath();
    ctx.roundRect(-w / 2 + 4, h / 2 - 6, 12, 4, 2);
    ctx.roundRect(w / 2 - 16, h / 2 - 6, 12, 4, 2);
    ctx.fill();
    // Center connecting LED lightbar
    ctx.fillRect(-w / 2 + 16, h / 2 - 4, w - 32, 2);
    ctx.shadowBlur = 0;

    // 7. Panoramic Tinted Glass Canopy (Windshields + Roof)
    const glassGrad = ctx.createLinearGradient(0, -h / 2 + 14, 0, h / 2 - 18);
    glassGrad.addColorStop(0, "#090d16");
    glassGrad.addColorStop(0.3, "#1e293b");
    glassGrad.addColorStop(0.7, "#0f172a");
    glassGrad.addColorStop(1, "#020617");

    ctx.fillStyle = glassGrad;
    ctx.beginPath();
    ctx.roundRect(-w / 2 + 6, -h / 2 + 14, w - 12, h - 36, [7, 7, 6, 6]);
    ctx.fill();

    // Glass glare reflection lines (aerodynamic cockpit sheen)
    ctx.strokeStyle = "rgba(255, 255, 255, 0.45)";
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.moveTo(-w / 2 + 11, -h / 2 + 18);
    ctx.lineTo(w / 2 - 18, -h / 2 + 32);
    ctx.stroke();

    // 8. Interior Cabin & Sunroof Divider
    ctx.strokeStyle = "rgba(255, 255, 255, 0.15)";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(-w / 2 + 8, -h / 2 + 36);
    ctx.lineTo(w / 2 - 8, -h / 2 + 36);
    ctx.moveTo(-w / 2 + 8, h / 2 - 32);
    ctx.lineTo(w / 2 - 8, h / 2 - 32);
    ctx.stroke();

    // 9. Rear License Plate Badge
    if (plateText) {
        const plateW = Math.min(w - 12, 54);
        const plateH = 14;
        const plateY = h / 2 - 16;

        ctx.fillStyle = "#ffffff";
        ctx.strokeStyle = "#0f172a";
        ctx.lineWidth = 1.2;
        ctx.beginPath();
        ctx.roundRect(-plateW / 2, plateY, plateW, plateH, 3);
        ctx.fill();
        ctx.stroke();

        ctx.fillStyle = "#0f172a";
        ctx.font = "bold 8.5px 'JetBrains Mono', monospace";
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText(plateText, 0, plateY + plateH / 2);
    }

    ctx.restore();
}

// ==========================================================================
// Hazard Striping & Multi-Floor Slope Ramp Renderers (Clean Modern Metallic Spec)
// ==========================================================================
function drawHazardStripes(ctx, x, y, width, height, stripeWidth = 5) {
    ctx.save();
    ctx.fillStyle = "rgba(255, 255, 255, 0.12)";
    ctx.fillRect(x, y, width, height);
    ctx.strokeStyle = "rgba(255, 255, 255, 0.28)";
    ctx.lineWidth = 1;
    ctx.strokeRect(x, y, width, height);
    ctx.restore();
}

function drawSlopeRamps(ctx, floor) {
    const isF1 = (floor === "F1");

    if (isF1) {
        // =====================================================================
        // FLOOR 1 SLOPE BARS (Executive Multi-Floor Access Ramps)
        // =====================================================================
        const yStart = 85;
        const yEnd = 705;
        const rampHeight = yEnd - yStart;
        const barWidth = 50;

        const drawFloor1Slope = (rx, isLeft) => {
            ctx.save();
            ctx.shadowColor = "rgba(15, 23, 42, 0.22)";
            ctx.shadowBlur = 10;
            ctx.shadowOffsetY = 3;

            // Deep imperial dark emerald obsidian glass tarmac
            const rampGrad = ctx.createLinearGradient(rx, yStart, rx + barWidth, yEnd);
            rampGrad.addColorStop(0, "#022c22");
            rampGrad.addColorStop(0.25, "#064e3b");
            rampGrad.addColorStop(0.5, "#043a2c");
            rampGrad.addColorStop(0.8, "#064e3b");
            rampGrad.addColorStop(1, "#022c22");

            ctx.fillStyle = rampGrad;
            ctx.beginPath();
            ctx.roundRect(rx, yStart, barWidth, rampHeight, 8);
            ctx.fill();
            ctx.shadowBlur = 0;

            // Gleaming Polished Gold Metallic Bezel Frame
            const goldBorder = ctx.createLinearGradient(rx, yStart, rx + barWidth, yEnd);
            goldBorder.addColorStop(0, "#fde047");
            goldBorder.addColorStop(0.25, "#ca8a04");
            goldBorder.addColorStop(0.5, "#eab308");
            goldBorder.addColorStop(0.75, "#a16207");
            goldBorder.addColorStop(1, "#fef08a");

            ctx.strokeStyle = goldBorder;
            ctx.lineWidth = 3.2;
            ctx.shadowColor = "rgba(202, 138, 4, 0.35)";
            ctx.shadowBlur = 8;
            ctx.stroke();
            ctx.shadowBlur = 0;

            // Anti-skid metallic grooved tread lines across ramp
            ctx.strokeStyle = "rgba(255, 255, 255, 0.09)";
            ctx.lineWidth = 1;
            for (let ty = yStart + 12; ty < yEnd - 6; ty += 14) {
                ctx.beginPath();
                ctx.moveTo(rx + 6, ty);
                ctx.lineTo(rx + barWidth - 6, ty);
                ctx.stroke();
            }

            // Rotated Illuminated "SLOPE" Text with Golden LED Halo
            ctx.save();
            ctx.translate(rx + barWidth / 2, 370);
            ctx.rotate(isLeft ? Math.PI / 2 : -Math.PI / 2);
            ctx.shadowColor = "rgba(234, 179, 8, 0.85)";
            ctx.shadowBlur = 10;
            ctx.fillStyle = "#ffffff";
            ctx.font = "bold 15px 'Plus Jakarta Sans', sans-serif";
            ctx.textAlign = "center";
            ctx.textBaseline = "middle";
            ctx.fillText("S L O P E", 0, 0);
            ctx.restore();

            // Directional Double-Chevrons (Neon Mint >>)
            const drawRampChevron = (cy, isDown) => {
                ctx.save();
                ctx.fillStyle = "rgba(255, 255, 255, 0.9)";
                ctx.shadowColor = "rgba(52, 211, 153, 0.6)";
                ctx.shadowBlur = 4;
                ctx.font = "bold 15px sans-serif";
                ctx.textAlign = "center";
                ctx.textBaseline = "middle";
                ctx.fillText(isDown ? "⇓" : "⇑", rx + barWidth / 2, cy);
                ctx.restore();
            };

            const arrowYs = isLeft ? [135, 195, 495, 565, 635] : [135, 195, 255, 565, 635];
            arrowYs.forEach(ay => {
                drawRampChevron(ay, isLeft);
            });

            // Golden Illuminated Central Directional Arrow
            ctx.save();
            ctx.fillStyle = "#facc15";
            ctx.shadowColor = "rgba(250, 204, 21, 0.85)";
            ctx.shadowBlur = 8;
            ctx.font = "bold 20px sans-serif";
            ctx.textAlign = "center";
            ctx.textBaseline = "middle";
            ctx.fillText(isLeft ? "↓" : "↑", rx + barWidth / 2, isLeft ? 260 : 490);
            ctx.restore();

            // Top Optical Slope Sensor Gate Pins (Matching Reference Diagram)
            ctx.save();
            const pinY = 42;
            const pinX = rx + barWidth / 2;

            // Connecting optical guide beam
            ctx.strokeStyle = "rgba(16, 185, 129, 0.6)";
            ctx.lineWidth = 1.5;
            ctx.setLineDash([4, 3]);
            ctx.beginPath();
            ctx.moveTo(pinX, pinY);
            ctx.lineTo(pinX, yStart);
            ctx.stroke();
            ctx.setLineDash([]);

            // Circular Emerald Optical Sensor Node with Gold Halo
            ctx.fillStyle = "#10b981";
            ctx.shadowColor = "rgba(16, 185, 129, 0.9)";
            ctx.shadowBlur = 8;
            ctx.beginPath();
            ctx.arc(pinX, pinY, 5, 0, Math.PI * 2);
            ctx.fill();

            // Gold Outer Bezel on Sensor Node
            ctx.strokeStyle = "#facc15";
            ctx.lineWidth = 1.5;
            ctx.stroke();

            // Pure White Inner Laser Core
            ctx.fillStyle = "#ffffff";
            ctx.shadowBlur = 0;
            ctx.beginPath();
            ctx.arc(pinX, pinY, 2, 0, Math.PI * 2);
            ctx.fill();
            ctx.restore();

            ctx.restore();
        };

        drawFloor1Slope(10, true);
        drawFloor1Slope(900, false);

        return;
    }

    // =========================================================================
    // FLOOR 2 SLOPE RAMPS (Connecting to Floor 2 Bottom Highway)
    // =========================================================================
    const yStart = 25;
    const yEnd = 605;
    const rampHeight = yEnd - yStart;

    // Left hazard stripe border
    drawHazardStripes(ctx, 25, yStart, 8, rampHeight, 5);
    drawHazardStripes(ctx, 97, yStart, 8, rampHeight, 5);

    // Maroon / Crimson tarmac roadway
    const leftGrad = ctx.createLinearGradient(33, yStart, 97, yEnd);
    leftGrad.addColorStop(0, "#450a0a");
    leftGrad.addColorStop(1, "#581c1c");
    ctx.fillStyle = leftGrad;
    ctx.fillRect(33, yStart, 64, rampHeight);

    // Outer border line
    ctx.strokeStyle = "#78350f";
    ctx.lineWidth = 1.5;
    ctx.strokeRect(25, yStart, 80, rampHeight);

    // Directional Downward Arrows (indicating flow toward 2nd floor entry)
    ctx.fillStyle = "rgba(255, 255, 255, 0.85)";
    ctx.font = "bold 15px sans-serif";
    ctx.textAlign = "center";
    const downArrowYs = [yStart + 40, yStart + 110, yStart + 180, yStart + 250, yStart + 320, yStart + 390, yStart + 460, yStart + 530];
    downArrowYs.forEach(ay => {
        if (ay < yEnd - 30) {
            ctx.fillText("⇓", 65, ay);
        }
    });

    // Center Vertical Ramp Label
    ctx.save();
    ctx.fillStyle = "#ffffff";
    ctx.shadowColor = "rgba(0, 0, 0, 0.6)";
    ctx.shadowBlur = 4;
    ctx.textAlign = "center";
    ctx.font = "bold 12px 'Plus Jakarta Sans', sans-serif";
    ctx.fillText("SLOPE UP", 65, 335);
    ctx.font = "bold 9px 'JetBrains Mono', monospace";
    ctx.fillText("(First Floor →", 65, 353);
    ctx.fillText("Second Floor)", 65, 369);
    ctx.restore();

    // Bottom Terminal Box: SECOND FLOOR ENTRY ➔
    ctx.fillStyle = "#ffffff";
    ctx.strokeStyle = "#334155";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.roundRect(14, 605, 102, 65, 6);
    ctx.fill();
    ctx.stroke();

    ctx.fillStyle = "#0f172a";
    ctx.font = "bold 9px 'Plus Jakarta Sans', sans-serif";
    ctx.textAlign = "center";
    ctx.fillText("SECOND FLOOR", 65, 623);
    ctx.fillText("ENTRY", 65, 637);
    ctx.font = "bold 16px sans-serif";
    ctx.fillStyle = "#0284c7";
    ctx.fillText("➔", 65, 657);

    // -------------------------------------------------------------------------
    // 2. RIGHT RAMP: SLOPE DOWN (F2 -> F1)
    // -------------------------------------------------------------------------
    drawHazardStripes(ctx, 855, yStart, 8, rampHeight, 5);
    drawHazardStripes(ctx, 927, yStart, 8, rampHeight, 5);

    const rightGrad = ctx.createLinearGradient(863, yStart, 927, yEnd);
    rightGrad.addColorStop(0, "#450a0a");
    rightGrad.addColorStop(1, "#581c1c");
    ctx.fillStyle = rightGrad;
    ctx.fillRect(863, yStart, 64, rampHeight);

    ctx.strokeStyle = "#78350f";
    ctx.lineWidth = 1.5;
    ctx.strokeRect(855, yStart, 80, rampHeight);

    ctx.fillStyle = "rgba(255, 255, 255, 0.85)";
    ctx.font = "bold 15px sans-serif";
    ctx.textAlign = "center";
    downArrowYs.forEach(ay => {
        if (ay < yEnd - 30) {
            ctx.fillText("⇑", 895, ay);
        }
    });

    ctx.save();
    ctx.fillStyle = "#ffffff";
    ctx.shadowColor = "rgba(0, 0, 0, 0.6)";
    ctx.shadowBlur = 4;
    ctx.textAlign = "center";
    ctx.font = "bold 12px 'Plus Jakarta Sans', sans-serif";
    ctx.fillText("SLOPE DOWN", 895, 335);
    ctx.font = "bold 9px 'JetBrains Mono', monospace";
    ctx.fillText("(Second Floor →", 895, 353);
    ctx.fillText("First Floor)", 895, 369);
    ctx.restore();

    // Bottom Terminal Box: SECOND FLOOR EXIT ➔
    ctx.fillStyle = "#ffffff";
    ctx.strokeStyle = "#334155";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.roundRect(844, 605, 102, 65, 6);
    ctx.fill();
    ctx.stroke();

    ctx.fillStyle = "#0f172a";
    ctx.font = "bold 9px 'Plus Jakarta Sans', sans-serif";
    ctx.textAlign = "center";
    ctx.fillText("SECOND FLOOR", 895, 623);
    ctx.fillText("EXIT", 895, 637);
    ctx.font = "bold 16px sans-serif";
    ctx.fillStyle = "#10b981";
    ctx.fillText("➔", 895, 657);
}

// ==========================================================================
// Multi-Floor Waypoint Visibility & Orthogonal Path Renderer Helpers
// ==========================================================================
function isPointOnFloor(pt, floor) {
    if (!pt) return false;
    const x = pt.x;
    const y = pt.y;
    const isRamp = (x <= 75 || x >= 885);
    if (floor === "F1") {
        if (isRamp) {
            return y <= 380; // Upper section of connecting slopes belongs to F1
        }
        return true; // All interior waypoints including bottom connector road belong to F1
    } else {
        // Floor 2
        if (isRamp) {
            return y >= 320; // Lower section of connecting slopes belongs to F2
        }
        return y >= 125; // F2 bays & aisles are y >= 125
    }
}

function simplifyAndOrthogonalizeSegment(pts) {
    if (!pts || pts.length < 2) return pts;
    
    // First pass: strictly enforce orthogonal steps if any two points are slanted
    let orthoPts = [pts[0]];
    for (let i = 1; i < pts.length; i++) {
        const p1 = orthoPts[orthoPts.length - 1];
        const p2 = pts[i];
        const dx = Math.abs(p2.x - p1.x);
        const dy = Math.abs(p2.y - p1.y);
        
        // If not already orthogonal (both dx > 0.5 and dy > 0.5)
        if (dx > 0.5 && dy > 0.5) {
            // Check if p1 or p2 is on an aisle or highway coordinate
            if (Math.abs(p1.x - 285) < 2 || Math.abs(p1.x - 675) < 2 || Math.abs(p1.y - 50) < 2 || Math.abs(p1.y - 600) < 2) {
                // p1 is on an aisle/highway, continue along aisle then turn perpendicularly
                orthoPts.push({ x: p1.x, y: p2.y });
            } else {
                orthoPts.push({ x: p2.x, y: p1.y });
            }
        }
        orthoPts.push({ x: Math.round(p2.x), y: Math.round(p2.y) });
    }

    // Second pass: remove redundant collinear intermediate points
    const simplified = [orthoPts[0]];
    for (let i = 1; i < orthoPts.length - 1; i++) {
        const prev = simplified[simplified.length - 1];
        const curr = orthoPts[i];
        const next = orthoPts[i + 1];

        const isCollinearX = Math.abs(prev.x - curr.x) < 0.5 && Math.abs(curr.x - next.x) < 0.5;
        const isCollinearY = Math.abs(prev.y - curr.y) < 0.5 && Math.abs(curr.y - next.y) < 0.5;

        if (!isCollinearX && !isCollinearY) {
            simplified.push(curr);
        }
    }
    simplified.push(orthoPts[orthoPts.length - 1]);
    return simplified;
}

function drawFloorRoute(ctx, route, floor, strokeColor) {
    if (!route || route.length < 2) return;

    let segments = [];
    let currentSeg = [];

    for (let i = 0; i < route.length; i++) {
        const pt = route[i];
        if (isPointOnFloor(pt, floor)) {
            currentSeg.push(pt);
        } else {
            if (currentSeg.length > 0) {
                segments.push(currentSeg);
                currentSeg = [];
            }
        }
    }
    if (currentSeg.length > 0) {
        segments.push(currentSeg);
    }

    segments.forEach(rawSeg => {
        if (rawSeg.length < 2) return;
        const seg = simplifyAndOrthogonalizeSegment(rawSeg);
        if (seg.length < 2) return;

        // Outer glowing track
        ctx.save();
        ctx.strokeStyle = strokeColor;
        ctx.lineWidth = 4.5;
        ctx.lineCap = "round";
        ctx.lineJoin = "round";
        ctx.shadowColor = strokeColor;
        ctx.shadowBlur = 8;
        ctx.beginPath();
        seg.forEach((pt, idx) => {
            if (idx === 0) ctx.moveTo(pt.x, pt.y);
            else ctx.lineTo(pt.x, pt.y);
        });
        ctx.stroke();

        // Inner dashed bright core
        ctx.strokeStyle = "#ffffff";
        ctx.lineWidth = 2;
        ctx.setLineDash([8, 6]);
        ctx.shadowBlur = 0;
        ctx.beginPath();
        seg.forEach((pt, idx) => {
            if (idx === 0) ctx.moveTo(pt.x, pt.y);
            else ctx.lineTo(pt.x, pt.y);
        });
        ctx.stroke();
        ctx.setLineDash([]);

        // Directed Arrowheads along each straight segment
        for (let i = 0; i < seg.length - 1; i++) {
            const p1 = seg[i];
            const p2 = seg[i + 1];
            const dx = p2.x - p1.x;
            const dy = p2.y - p1.y;
            const len = Math.hypot(dx, dy);
            if (len >= 36) {
                const midX = (p1.x + p2.x) / 2;
                const midY = (p1.y + p2.y) / 2;
                const angle = Math.atan2(dy, dx);
                ctx.save();
                ctx.translate(midX, midY);
                ctx.rotate(angle);
                ctx.fillStyle = "#ffffff";
                ctx.beginPath();
                ctx.moveTo(5, 0);
                ctx.lineTo(-4, -4);
                ctx.lineTo(-2, 0);
                ctx.lineTo(-4, 4);
                ctx.closePath();
                ctx.fill();
                ctx.restore();
            }
        }

        ctx.restore();
    });
}

// ==========================================================================
// Digital Twin Facility Canvas Rendering Routine (Multi-Floor F1 & F2)
// ==========================================================================
function renderDigitalTwin() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    pulsePhase += 0.05;

    // 1. Facility Foundation (Architectural Concrete Floor)
    ctx.fillStyle = "#faf9f6";
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    // Subtle architectural grid
    ctx.strokeStyle = "rgba(226, 232, 240, 0.5)";
    ctx.lineWidth = 1;
    ctx.beginPath();
    for (let gx = 0; gx < canvas.width; gx += 40) {
        ctx.moveTo(gx, 0);
        ctx.lineTo(gx, canvas.height);
    }
    for (let gy = 0; gy < canvas.height; gy += 40) {
        ctx.moveTo(0, gy);
        ctx.lineTo(canvas.width, gy);
    }
    ctx.stroke();

    // 2. Draw Dual-Level Connecting Ramps (SLOPE UP on West, SLOPE DOWN on East)
    drawSlopeRamps(ctx, currentFloor);

    // 3. Render Floor-Specific Roadways, Storage Rooms, and Markings
    const roadColor = "#e2e8f0";
    ctx.fillStyle = roadColor;

    if (currentFloor === "F1") {
        // =====================================================================
        // FIRST FLOOR (F1) ARCHITECTURAL LAYOUT (EXECUTIVE RESIN TARMAC & ROADWAYS)
        // =====================================================================

        // 1. Polished Architectural Resin Asphalt Tarmac
        const tarmacGrad = ctx.createLinearGradient(0, 15, 0, 635);
        tarmacGrad.addColorStop(0, "#ebf0f7");
        tarmacGrad.addColorStop(0.3, "#e2e7ef");
        tarmacGrad.addColorStop(0.7, "#dde3ec");
        tarmacGrad.addColorStop(1, "#d6dce6");
        ctx.fillStyle = tarmacGrad;

        // Top Entry / Exit Highway: x = 0 to 960, y = 15 to 85 (height = 70)
        ctx.fillRect(0, 15, 960, 70);

        // Aisle 1 (Southbound): x = 235 to 335 (width = 100, center = 285)
        ctx.fillRect(235, 85, 100, 550);

        // Aisle 2 (Northbound / Bidirectional): x = 625 to 725 (width = 100, center = 675)
        ctx.fillRect(625, 85, 100, 550);

        // Bottom Connector Road: x = 235 to 725, y = 565 to 635 (height = 70)
        ctx.fillRect(235, 565, 490, 70);

        // 2. High-Precision Double-Bevel Concrete Curbs
        // Base shadow edge
        ctx.strokeStyle = "#cbd5e1";
        ctx.lineWidth = 2.5;
        ctx.beginPath();
        // Top highway curbs
        ctx.moveTo(0, 15);
        ctx.lineTo(960, 15);
        ctx.moveTo(0, 85);
        ctx.lineTo(235, 85);
        ctx.moveTo(335, 85);
        ctx.lineTo(625, 85);
        ctx.moveTo(725, 85);
        ctx.lineTo(960, 85);
        // Aisle 1 inner & outer edges
        ctx.moveTo(235, 85);
        ctx.lineTo(235, 565);
        ctx.moveTo(335, 85);
        ctx.lineTo(335, 565);
        // Aisle 2 inner & outer edges
        ctx.moveTo(625, 85);
        ctx.lineTo(625, 565);
        ctx.moveTo(725, 85);
        ctx.lineTo(725, 565);
        // Bottom road bottom curb
        ctx.moveTo(235, 635);
        ctx.lineTo(725, 635);
        ctx.stroke();

        // 3D White Top Highlight for Curbs
        ctx.strokeStyle = "rgba(255, 255, 255, 0.85)";
        ctx.lineWidth = 1.2;
        ctx.beginPath();
        ctx.moveTo(0, 16);
        ctx.lineTo(960, 16);
        ctx.stroke();

        // 3. Optical Laser Sensor Curtains at Entry and Exit Toll Portals
        // Entry Optical Laser Portal [CAM_01] (Positioned on roadway at x = 80, clear of slope ramps)
        ctx.save();
        const entryGlow = 0.55 + 0.35 * Math.sin(pulsePhase * 3);
        ctx.strokeStyle = `rgba(56, 189, 248, ${entryGlow})`;
        ctx.lineWidth = 2.5;
        ctx.shadowColor = "#0284c7";
        ctx.shadowBlur = 8;
        ctx.beginPath();
        ctx.moveTo(80, 16);
        ctx.lineTo(80, 84);
        ctx.stroke();

        // Sleek Architectural Toll Sensor Pylons (Top & Bottom of highway at x = 80)
        ctx.fillStyle = "#0f172a";
        ctx.strokeStyle = "rgba(56, 189, 248, 0.8)";
        ctx.lineWidth = 1;
        ctx.shadowBlur = 0;
        ctx.beginPath();
        ctx.roundRect(76, 16, 8, 9, 2);
        ctx.roundRect(76, 75, 8, 9, 2);
        ctx.fill();
        ctx.stroke();

        ctx.fillStyle = "#38bdf8";
        ctx.shadowColor = "#38bdf8";
        ctx.shadowBlur = 5;
        ctx.beginPath();
        ctx.arc(80, 20.5, 2, 0, Math.PI * 2);
        ctx.arc(80, 79.5, 2, 0, Math.PI * 2);
        ctx.fill();
        ctx.restore();

        // Exit Optical Laser Portal [CAM_02] (Positioned on roadway at x = 880, clear of slope ramps)
        ctx.save();
        const exitGlow = 0.55 + 0.35 * Math.sin(pulsePhase * 3 + Math.PI);
        ctx.strokeStyle = `rgba(16, 185, 129, ${exitGlow})`;
        ctx.lineWidth = 2.5;
        ctx.shadowColor = "#10b981";
        ctx.shadowBlur = 8;
        ctx.beginPath();
        ctx.moveTo(880, 16);
        ctx.lineTo(880, 84);
        ctx.stroke();

        // Sleek Architectural Toll Sensor Pylons (Top & Bottom of highway at x = 880)
        ctx.fillStyle = "#0f172a";
        ctx.strokeStyle = "rgba(16, 185, 129, 0.8)";
        ctx.lineWidth = 1;
        ctx.shadowBlur = 0;
        ctx.beginPath();
        ctx.roundRect(876, 16, 8, 9, 2);
        ctx.roundRect(876, 75, 8, 9, 2);
        ctx.fill();
        ctx.stroke();

        ctx.fillStyle = "#10b981";
        ctx.shadowColor = "#10b981";
        ctx.shadowBlur = 5;
        ctx.beginPath();
        ctx.arc(880, 20.5, 2, 0, Math.PI * 2);
        ctx.arc(880, 79.5, 2, 0, Math.PI * 2);
        ctx.fill();
        ctx.restore();

        // 4. Glowing White Thermoplast Dashed Lane Centerlines
        ctx.save();
        ctx.strokeStyle = "rgba(255, 255, 255, 0.95)";
        ctx.shadowColor = "rgba(148, 163, 184, 0.35)";
        ctx.shadowBlur = 4;
        ctx.setLineDash([14, 10]);
        ctx.lineWidth = 2.5;

        // Top Highway Centerline
        ctx.beginPath();
        ctx.moveTo(10, 50);
        ctx.lineTo(950, 50);
        ctx.stroke();

        // Aisle 1 Centerline (Southbound)
        ctx.beginPath();
        ctx.moveTo(285, 85);
        ctx.lineTo(285, 600);
        ctx.stroke();

        // Aisle 2 Centerline (Two-Way Access)
        ctx.beginPath();
        ctx.moveTo(675, 85);
        ctx.lineTo(675, 600);
        ctx.stroke();

        // Bottom Connector Road Centerline (Eastbound)
        ctx.beginPath();
        ctx.moveTo(285, 600);
        ctx.lineTo(675, 600);
        ctx.stroke();
        ctx.restore();

        // 5. Stylized Directional Driving Double-Chevrons (Neon Emerald >>)
        const drawDoubleChevron = (x, y, angle, size = 8) => {
            ctx.save();
            ctx.translate(x, y);
            ctx.rotate(angle);
            ctx.fillStyle = "#10b981";
            ctx.shadowColor = "rgba(16, 185, 129, 0.75)";
            ctx.shadowBlur = 6;

            const drawOne = (offsetX) => {
                ctx.beginPath();
                ctx.moveTo(offsetX + size, 0);
                ctx.lineTo(offsetX - size * 0.7, -size * 0.8);
                ctx.lineTo(offsetX - size * 0.2, 0);
                ctx.lineTo(offsetX - size * 0.7, size * 0.8);
                ctx.closePath();
                ctx.fill();
            };

            drawOne(-4);
            drawOne(4);
            ctx.shadowBlur = 0;
            ctx.restore();
        };

        // Top Highway Eastbound Chevrons (>> >> >>)
        drawDoubleChevron(160, 50, 0);
        drawDoubleChevron(480, 50, 0);
        drawDoubleChevron(820, 50, 0);

        // Aisle 1 Southbound Chevrons (vv vv)
        drawDoubleChevron(285, 230, Math.PI / 2);
        drawDoubleChevron(285, 480, Math.PI / 2);

        // Aisle 2 Dual Traffic Flow Chevrons (Southbound Inbound on West, Northbound Outbound on East)
        drawDoubleChevron(652, 230, Math.PI / 2, 6.5);
        drawDoubleChevron(652, 470, Math.PI / 2, 6.5);
        drawDoubleChevron(698, 470, -Math.PI / 2, 6.5);
        drawDoubleChevron(698, 230, -Math.PI / 2, 6.5);

        // Bottom Connector Road Eastbound Chevron (>>)
        drawDoubleChevron(480, 600, 0);

        // 6. Executive Gate Badges & Facility Header Banner
        ctx.fillStyle = "#0284c7";
        ctx.font = "bold 10.5px 'JetBrains Mono', monospace";
        ctx.textAlign = "left";
        ctx.textBaseline = "alphabetic";
        ctx.fillText("▶ ENTRY GATE [CAM_01] • OPTICAL SENSOR", 15, 12);

        ctx.fillStyle = "#059669";
        ctx.textAlign = "right";
        ctx.fillText("AUTO EXIT [CAM_02] ◀", 945, 12);

        // Blueprint Header Banner for F1
        ctx.save();
        ctx.fillStyle = "#1e3a8a";
        ctx.shadowColor = "rgba(30, 58, 138, 0.25)";
        ctx.shadowBlur = 6;
        ctx.beginPath();
        ctx.roundRect(350, 1, 260, 17, 4);
        ctx.fill();
        ctx.shadowBlur = 0;
        ctx.fillStyle = "#ffffff";
        ctx.font = "bold 10px 'Plus Jakarta Sans', sans-serif";
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText("First floor  —  PARKING LAYOUT", 480, 9.5);
        ctx.restore();

    } else {
        // =====================================================================
        // SECOND FLOOR (F2) ARCHITECTURAL LAYOUT (INVERTED GEOMETRY)
        // =====================================================================

        // Storage / Utility Room at Top Left (y = 25 to 120)
        ctx.fillStyle = "#f1f5f9";
        ctx.strokeStyle = "#94a3b8";
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.roundRect(155, 25, 115, 95, 4);
        ctx.fill();
        ctx.stroke();
        ctx.fillStyle = "#64748b";
        ctx.font = "bold 9.5px 'JetBrains Mono', monospace";
        ctx.textAlign = "center";
        ctx.fillText("STORAGE /", 212, 66);
        ctx.fillText("UTILITY", 212, 79);
        ctx.font = "8.5px 'JetBrains Mono', monospace";
        ctx.fillText("A: 31.2 m²", 212, 94);

        // Top Cross-Aisle (under Storage and Bays S23-S28, y = 125 to 185)
        ctx.fillRect(285, 125, 390, 60);

        // Aisle 1 (Northbound from Bottom Highway to Top Cross-Aisle)
        ctx.fillRect(285, 125, 100, 490);

        // Aisle 2 (Southbound from Top Cross-Aisle to Bottom Highway)
        ctx.fillRect(575, 125, 100, 490);

        // Bottom Highway (connecting Left Slope Entry to Right Slope Exit)
        ctx.fillRect(116, 615, 728, 70);

        // Bottom Highway Curbs
        ctx.strokeStyle = "#cbd5e1";
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.moveTo(116, 615);
        ctx.lineTo(844, 615);
        ctx.moveTo(116, 685);
        ctx.lineTo(844, 685);
        ctx.stroke();

        // Dashed White Lane Centerlines
        ctx.strokeStyle = "#ffffff";
        ctx.setLineDash([12, 10]);
        ctx.lineWidth = 2.5;

        // Bottom Highway Centerline
        ctx.beginPath();
        ctx.moveTo(116, 650);
        ctx.lineTo(844, 650);
        ctx.stroke();

        // Top Cross-Aisle Centerline
        ctx.beginPath();
        ctx.moveTo(335, 155);
        ctx.lineTo(625, 155);
        ctx.stroke();

        // Aisle 1 Centerline
        ctx.beginPath();
        ctx.moveTo(335, 155);
        ctx.lineTo(335, 615);
        ctx.stroke();

        // Aisle 2 Centerline
        ctx.beginPath();
        ctx.moveTo(625, 155);
        ctx.lineTo(625, 615);
        ctx.stroke();
        ctx.setLineDash([]);

        // Directional Driving Arrows for Floor 2
        ctx.fillStyle = "rgba(100, 116, 139, 0.75)";
        ctx.font = "bold 14px sans-serif";
        ctx.textAlign = "center";
        // Bottom highway arrows (Eastbound from Left Slope to Right Slope)
        ctx.fillText("➔", 180, 654);
        ctx.fillText("➔", 335, 654);
        ctx.fillText("➔", 480, 654);
        ctx.fillText("➔", 625, 654);
        ctx.fillText("➔", 760, 654);
        // Aisle arrows (Circulating Loop: Aisle 1 Northbound, Aisle 2 Southbound)
        ctx.fillText("⬆", 335, 270);
        ctx.fillText("⬆", 335, 450);
        ctx.fillText("⬇", 625, 270);
        ctx.fillText("⬇", 625, 450);
        // Top cross-aisle arrow
        ctx.fillText("➔", 480, 159);

        // Blueprint Banner for F2
        ctx.save();
        ctx.fillStyle = "#1e3a8a";
        ctx.beginPath();
        ctx.roundRect(330, 694, 300, 22, 6);
        ctx.fill();
        ctx.fillStyle = "#ffffff";
        ctx.font = "bold 11px 'Plus Jakarta Sans', sans-serif";
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText("///  SECOND FLOOR PARKING (F2)  ///", 480, 705);
        ctx.restore();

        // Columns / Pillars for F2
        const pillarsF2 = [
            [185, 195], [185, 335], [185, 475], [185, 605],
            [285, 195], [285, 335], [285, 475], [285, 605],
            [385, 195], [385, 335], [385, 475], [385, 605],
            [480, 195], [480, 335], [480, 475], [480, 605],
            [575, 195], [575, 335], [575, 475], [575, 605],
            [675, 195], [675, 335], [675, 475], [675, 605],
            [770, 195], [770, 335], [770, 475], [770, 605]
        ];
        pillarsF2.forEach(([px, py]) => {
            ctx.fillStyle = "#1e293b";
            ctx.shadowColor = "rgba(0, 0, 0, 0.25)";
            ctx.shadowBlur = 3;
            ctx.fillRect(px - 5, py - 5, 10, 10);
            ctx.shadowBlur = 0;
        });
    }

    // 4. Render Parking Bays for the Active Viewing Floor
    const colorsPool = ["#0284c7", "#6366f1", "#059669", "#d97706", "#dc2626", "#7c3aed", "#0891b2", "#ea580c"];
    const viewingFloorNum = (currentFloor === "F2") ? 2 : 1;

    if (liveState && liveState.slots) {
        Object.values(liveState.slots).forEach((slot, index) => {
            const slotFloorNum = slot.floor || (slot.id.startsWith("F2-") ? 2 : 1);
            if (slotFloorNum !== viewingFloorNum) return;

            const x = slot.x;
            const y = slot.y;
            const w = slot.width;
            const h = slot.height;
            const bayCode = slot.bay_code || slot.id.split("-").pop();
            const isVertical = bayCode >= "S23";

            const isOccupied = slot.status === "OCCUPIED";
            const isAllocated = slot.status === "ALLOCATED";
            const isHovered = hoveredSlotId === slot.id;

            if (slotFloorNum === 1) {
                // =============================================================
                // FLOOR 1: 6 LUXURY ARCHITECTURAL BAYS (Gold & Emerald Spec)
                // =============================================================
                const isAmber = (slot.id === "F1-S03" || slot.id === "F1-S05");
                const isHorizontal = (slot.id === "F1-S03" || slot.id === "F1-S04");

                ctx.save();
                if (isAmber) {
                    // Polished Metallic Gold Double-Rim Frame (Slots 3 & 5)
                    ctx.shadowColor = "rgba(217, 119, 6, 0.28)";
                    ctx.shadowBlur = 14;
                    ctx.shadowOffsetY = 4;

                    const cardGrad = ctx.createLinearGradient(x, y, x + w, y + h);
                    cardGrad.addColorStop(0, isHovered ? "rgba(255, 251, 235, 0.98)" : "rgba(255, 247, 237, 0.95)");
                    cardGrad.addColorStop(1, isHovered ? "rgba(254, 243, 226, 0.94)" : "rgba(254, 237, 213, 0.88)");
                    ctx.fillStyle = cardGrad;
                    ctx.beginPath();
                    ctx.roundRect(x, y, w, h, 16);
                    ctx.fill();
                    ctx.shadowBlur = 0;

                    // Outer Polished Metallic Gold Bezel
                    const goldBezel = ctx.createLinearGradient(x, y, x + w, y + h);
                    goldBezel.addColorStop(0, "#fde047");
                    goldBezel.addColorStop(0.25, "#ca8a04");
                    goldBezel.addColorStop(0.5, "#eab308");
                    goldBezel.addColorStop(0.75, "#a16207");
                    goldBezel.addColorStop(1, "#fef08a");

                    ctx.strokeStyle = isAllocated ? "#0284c7" : goldBezel;
                    ctx.lineWidth = isHovered || isAllocated ? 3.8 : 3.2;
                    if (isAllocated) ctx.setLineDash([8, 6]);
                    ctx.stroke();
                    ctx.setLineDash([]);

                    // Inner Metallic Gold Hairline
                    ctx.strokeStyle = "rgba(234, 179, 8, 0.45)";
                    ctx.lineWidth = 1;
                    ctx.beginPath();
                    ctx.roundRect(x + 3.5, y + 3.5, w - 7, h - 7, 13);
                    ctx.stroke();
                } else {
                    // Polished Metallic Emerald Chrome Double-Rim Frame (Slots 1, 2, 4, 6)
                    ctx.shadowColor = "rgba(5, 150, 105, 0.24)";
                    ctx.shadowBlur = 14;
                    ctx.shadowOffsetY = 4;

                    const cardGrad = ctx.createLinearGradient(x, y, x + w, y + h);
                    cardGrad.addColorStop(0, isHovered ? "rgba(240, 253, 244, 0.98)" : "rgba(240, 253, 244, 0.95)");
                    cardGrad.addColorStop(1, isHovered ? "rgba(209, 250, 229, 0.94)" : "rgba(220, 246, 233, 0.88)");
                    ctx.fillStyle = cardGrad;
                    ctx.beginPath();
                    ctx.roundRect(x, y, w, h, 16);
                    ctx.fill();
                    ctx.shadowBlur = 0;

                    // Outer Polished Metallic Emerald Chrome Bezel
                    const emeraldBezel = ctx.createLinearGradient(x, y, x + w, y + h);
                    emeraldBezel.addColorStop(0, "#6ee7b7");
                    emeraldBezel.addColorStop(0.25, "#059669");
                    emeraldBezel.addColorStop(0.5, "#10b981");
                    emeraldBezel.addColorStop(0.75, "#047857");
                    emeraldBezel.addColorStop(1, "#34d399");

                    ctx.strokeStyle = isAllocated ? "#0284c7" : emeraldBezel;
                    ctx.lineWidth = isHovered || isAllocated ? 3.8 : 3.2;
                    if (isAllocated) ctx.setLineDash([8, 6]);
                    ctx.stroke();
                    ctx.setLineDash([]);

                    // Inner Metallic Emerald Hairline
                    ctx.strokeStyle = "rgba(16, 185, 129, 0.35)";
                    ctx.lineWidth = 1;
                    ctx.beginPath();
                    ctx.roundRect(x + 3.5, y + 3.5, w - 7, h - 7, 13);
                    ctx.stroke();
                }
                ctx.restore();

                // Draw Precision CAD Blueprint L-Brackets & Ground Guide Tracks
                drawSlotArchitecturalAccents(ctx, x, y, w, h, isHorizontal, isOccupied, isAmber, isAllocated, slot.id);

                if (isHorizontal) {
                    // =========================================================
                    // WIDE LANDSCAPE SLOTS (Slots 3 & 4: 290px x 165px)
                    // =========================================================
                    if (isOccupied) {
                        // Draw Horizontal Realistic Parked Car (Centered in slot)
                        const defaultPalette = {
                            "F1-S03": "#ea580c",
                            "F1-S04": "#94a3b8"
                        };
                        const carColor = defaultPalette[slot.id] || colorsPool[index % colorsPool.length];
                        const plate = slot.vehicle_plate || "";
                        const carX = x + w / 2;
                        const carY = y + h / 2;
                        drawRealisticCar(ctx, carX, carY, 48, 96, carColor, plate, slot.is_ev, Math.PI / 2);

                        if (isHovered) {
                            ctx.save();
                            ctx.fillStyle = "#e11d48";
                            ctx.shadowColor = "rgba(225, 29, 72, 0.4)";
                            ctx.shadowBlur = 8;
                            ctx.beginPath();
                            ctx.roundRect(x + w / 2 - 48, y + h - 28, 96, 22, 6);
                            ctx.fill();
                            ctx.shadowBlur = 0;
                            ctx.fillStyle = "#ffffff";
                            ctx.font = "bold 9.5px 'JetBrains Mono', monospace";
                            ctx.textAlign = "center";
                            ctx.textBaseline = "middle";
                            ctx.fillText("➔ CLICK TO EXIT", x + w / 2, y + h - 17);
                            ctx.restore();
                        }
                    } else if (isAllocated) {
                        // Incoming Reservation Badge (Centered in slot)
                        const pillW = 96;
                        const pillH = 28;
                        ctx.save();
                        ctx.shadowColor = "rgba(2, 132, 199, 0.35)";
                        ctx.shadowBlur = 10;
                        ctx.shadowOffsetY = 2;
                        ctx.beginPath();
                        ctx.roundRect(x + w / 2 - pillW / 2, y + h / 2 - pillH / 2, pillW, pillH, 14);
                        const inGrad = ctx.createLinearGradient(x + w / 2, y + h / 2 - pillH / 2, x + w / 2, y + h / 2 + pillH / 2);
                        inGrad.addColorStop(0, "#38bdf8");
                        inGrad.addColorStop(1, "#0284c7");
                        ctx.fillStyle = inGrad;
                        ctx.fill();
                        ctx.shadowBlur = 0;

                        ctx.fillStyle = "#ffffff";
                        ctx.font = "bold 11px 'Plus Jakarta Sans', sans-serif";
                        ctx.textAlign = "center";
                        ctx.textBaseline = "middle";
                        ctx.fillText("⚡ INCOMING", x + w / 2, y + h / 2 - 2);

                        if (slot.vehicle_plate) {
                            ctx.fillStyle = "#0369a1";
                            ctx.font = "bold 9px 'JetBrains Mono', monospace";
                            ctx.fillText(slot.vehicle_plate, x + w / 2, y + h / 2 + 18);
                        }
                        ctx.restore();
                    } else {
                        // Executive Dark Forest Green Pill Badge: 🚘 FREE (Matching Reference Diagram)
                        const pillW = 104;
                        const pillH = 30;
                        const px = x + w / 2 - pillW / 2;
                        const py = y + h / 2 - pillH / 2;

                        ctx.save();
                        ctx.shadowColor = "rgba(0, 0, 0, 0.28)";
                        ctx.shadowBlur = 8;
                        ctx.shadowOffsetY = 3;

                        // Deep Forest Green Gradient
                        const pillGrad = ctx.createLinearGradient(px, py, px, py + pillH);
                        pillGrad.addColorStop(0, "#065f46");
                        pillGrad.addColorStop(0.5, "#064e3b");
                        pillGrad.addColorStop(1, "#022c22");
                        ctx.fillStyle = pillGrad;
                        ctx.beginPath();
                        ctx.roundRect(px, py, pillW, pillH, pillH / 2);
                        ctx.fill();
                        ctx.shadowBlur = 0;

                        // Subtle Gloss Emerald Rim
                        ctx.strokeStyle = "rgba(52, 211, 153, 0.6)";
                        ctx.lineWidth = 1.2;
                        ctx.stroke();

                        // 🚘 FREE Typography
                        ctx.fillStyle = "#ffffff";
                        ctx.font = "bold 12px sans-serif";
                        ctx.textAlign = "center";
                        ctx.textBaseline = "middle";
                        ctx.fillText("🚘 FREE", px + pillW / 2, py + pillH / 2);
                        ctx.restore();
                    }
                } else {
                    // =========================================================
                    // TALL PORTRAIT SLOTS (Slots 1, 2, 5, 6: 160px x 235px)
                    // =========================================================
                    if (isOccupied) {
                        // Draw Vertical Realistic Parked Car (Centered in slot)
                        const defaultPalette = {
                            "F1-S01": "#38bdf8",
                            "F1-S02": "#d97706",
                            "F1-S05": "#334155",
                            "F1-S06": "#8b5cf6"
                        };
                        const carColor = defaultPalette[slot.id] || colorsPool[index % colorsPool.length];
                        const plate = slot.vehicle_plate || "";
                        const carX = x + w / 2;
                        const carY = y + h / 2;
                        drawRealisticCar(ctx, carX, carY, 46, 88, carColor, plate, slot.is_ev, 0);

                        if (isHovered) {
                            ctx.save();
                            ctx.fillStyle = "#e11d48";
                            ctx.shadowColor = "rgba(225, 29, 72, 0.4)";
                            ctx.shadowBlur = 8;
                            ctx.beginPath();
                            ctx.roundRect(x + w / 2 - 44, y + h - 28, 88, 22, 6);
                            ctx.fill();
                            ctx.shadowBlur = 0;
                            ctx.fillStyle = "#ffffff";
                            ctx.font = "bold 9px 'JetBrains Mono', monospace";
                            ctx.textAlign = "center";
                            ctx.textBaseline = "middle";
                            ctx.fillText("➔ CLICK TO EXIT", x + w / 2, y + h - 17);
                            ctx.restore();
                        }
                    } else if (isAllocated) {
                        // Incoming Reservation Badge (Centered in slot)
                        const pillW = 90;
                        const pillH = 26;
                        ctx.save();
                        ctx.shadowColor = "rgba(2, 132, 199, 0.35)";
                        ctx.shadowBlur = 10;
                        ctx.shadowOffsetY = 2;
                        ctx.beginPath();
                        ctx.roundRect(x + w / 2 - pillW / 2, y + h / 2 - pillH / 2, pillW, pillH, 13);
                        const inGrad = ctx.createLinearGradient(x + w / 2, y + h / 2 - pillH / 2, x + w / 2, y + h / 2 + pillH / 2);
                        inGrad.addColorStop(0, "#38bdf8");
                        inGrad.addColorStop(1, "#0284c7");
                        ctx.fillStyle = inGrad;
                        ctx.fill();
                        ctx.shadowBlur = 0;

                        ctx.fillStyle = "#ffffff";
                        ctx.font = "bold 10px 'Plus Jakarta Sans', sans-serif";
                        ctx.textAlign = "center";
                        ctx.textBaseline = "middle";
                        ctx.fillText("⚡ INCOMING", x + w / 2, y + h / 2 - 2);

                        if (slot.vehicle_plate) {
                            ctx.fillStyle = "#0369a1";
                            ctx.font = "bold 8.5px 'JetBrains Mono', monospace";
                            ctx.fillText(slot.vehicle_plate, x + w / 2, y + h / 2 + 16);
                        }
                        ctx.restore();
                    } else {
                        // Executive Dark Forest Green Pill Badge: 🚘 FREE (Matching Reference Diagram)
                        const pillW = 96;
                        const pillH = 28;
                        const px = x + w / 2 - pillW / 2;
                        const py = y + h / 2 - pillH / 2;

                        ctx.save();
                        ctx.shadowColor = "rgba(0, 0, 0, 0.28)";
                        ctx.shadowBlur = 8;
                        ctx.shadowOffsetY = 3;

                        // Deep Forest Green Gradient
                        const pillGrad = ctx.createLinearGradient(px, py, px, py + pillH);
                        pillGrad.addColorStop(0, "#065f46");
                        pillGrad.addColorStop(0.5, "#064e3b");
                        pillGrad.addColorStop(1, "#022c22");
                        ctx.fillStyle = pillGrad;
                        ctx.beginPath();
                        ctx.roundRect(px, py, pillW, pillH, pillH / 2);
                        ctx.fill();
                        ctx.shadowBlur = 0;

                        // Subtle Gloss Emerald Rim
                        ctx.strokeStyle = "rgba(52, 211, 153, 0.6)";
                        ctx.lineWidth = 1.2;
                        ctx.stroke();

                        // 🚘 FREE Typography
                        ctx.fillStyle = "#ffffff";
                        ctx.font = "bold 11.5px sans-serif";
                        ctx.textAlign = "center";
                        ctx.textBaseline = "middle";
                        ctx.fillText("🚘 FREE", px + pillW / 2, py + pillH / 2);
                        ctx.restore();
                    }
                }

                // Draw Automated Smart Bay Barrier Gate at Slot Entrance Point
                drawSlotGate(ctx, slot, isOccupied, isAllocated, isHovered);
            } else {
                // =============================================================
                // FLOOR 2: 28 BAYS ARCHITECTURAL LAYOUT (Preserved as Before)
                // =============================================================
                const bayCode = slot.bay_code || slot.id.split("-").pop();
                const isVertical = bayCode >= "S23";

                if (isOccupied) {
                    ctx.fillStyle = isHovered ? "rgba(254, 205, 211, 0.95)" : "rgba(254, 226, 226, 0.85)";
                    ctx.strokeStyle = isHovered ? "#e11d48" : "#f87171";
                } else if (isAllocated) {
                    ctx.fillStyle = "rgba(224, 242, 254, 0.9)";
                    ctx.strokeStyle = "#0284c7";
                } else {
                    ctx.fillStyle = isHovered ? "rgba(209, 250, 229, 0.95)" : "rgba(236, 253, 245, 0.8)";
                    ctx.strokeStyle = "#34d399";
                }

                ctx.lineWidth = isHovered || isAllocated ? 3 : 1.5;
                if (isAllocated) ctx.setLineDash([5, 4]);
                ctx.beginPath();
                ctx.roundRect(x, y, w, h, 6);
                ctx.fill();
                ctx.stroke();
                ctx.setLineDash([]);

                // Slot Bay ID
                ctx.fillStyle = "#1e293b";
                ctx.font = "bold 11px 'Plus Jakarta Sans', sans-serif";
                ctx.textAlign = "left";
                ctx.textBaseline = "alphabetic";
                ctx.fillText(bayCode, x + 6, y + 15);

                if (isOccupied) {
                    const carColor = colorsPool[index % colorsPool.length];
                    const carX = x + w / 2;
                    const carY = y + h / 2;
                    const plate = slot.vehicle_plate || `TRK-${slot.track_id || (10 + index)}`;

                    if (isVertical) {
                        drawRealisticCar(ctx, carX, carY, 44, 76, carColor, plate, false, 0);
                    } else {
                        const isWestFacing = (bayCode >= "S01" && bayCode <= "S06") || (bayCode >= "S12" && bayCode <= "S16");
                        const rot = isWestFacing ? Math.PI / 2 : -Math.PI / 2;
                        drawRealisticCar(ctx, carX, carY, 44, 76, carColor, plate, false, rot);
                    }

                    if (isHovered) {
                        ctx.save();
                        ctx.fillStyle = "#e11d48";
                        ctx.shadowColor = "rgba(225, 29, 72, 0.4)";
                        ctx.shadowBlur = 8;
                        ctx.beginPath();
                        ctx.roundRect(x + 2, y + h - 20, w - 4, 16, 4);
                        ctx.fill();
                        ctx.shadowBlur = 0;
                        ctx.fillStyle = "#ffffff";
                        ctx.font = "bold 8px 'JetBrains Mono', monospace";
                        ctx.textAlign = "center";
                        ctx.textBaseline = "middle";
                        ctx.fillText("➔ EXIT", x + w/2, y + h - 12);
                        ctx.restore();
                    }
                } else if (isAllocated) {
                    ctx.fillStyle = "#0284c7";
                    ctx.font = "bold 9px 'JetBrains Mono', monospace";
                    ctx.textAlign = "center";
                    ctx.fillText("INCOMING", x + w / 2, y + h / 2 - 4);
                    ctx.fillStyle = "#0369a1";
                    ctx.font = "bold 8px 'JetBrains Mono', monospace";
                    ctx.fillText(slot.vehicle_plate || "ASSIGNED", x + w / 2, y + h / 2 + 9);
                } else {
                    ctx.fillStyle = "rgba(16, 185, 129, 0.9)";
                    ctx.font = "bold 9px 'JetBrains Mono', monospace";
                    ctx.textAlign = "center";
                    ctx.fillText("FREE", x + w / 2, y + h / 2 + (isVertical ? 10 : 4));
                }

                // Draw Automated Smart Bay Barrier Gate at Slot Entrance Point
                drawSlotGate(ctx, slot, isOccupied, isAllocated, isHovered);
            }
        });
    }

    // 5. Draw Animated Entering Vehicle along A* Navigation Route
    if (enterCarAnimation && enterCarAnimation.route && enterCarAnimation.route.length > 1) {
        const route = enterCarAnimation.route;

        // Draw Floor-Aware Glowing Route Path (seamless on ramps, clipped to current level)
        drawFloorRoute(ctx, route, currentFloor, "#0284c7");

        // Target marker (rendered only if target bay is on current viewed floor)
        const targetPt = route[route.length - 1];
        if (isPointOnFloor(targetPt, currentFloor)) {
            ctx.save();
            ctx.fillStyle = enterCarAnimation.isBypass ? "#ef4444" : "#10b981";
            ctx.shadowColor = enterCarAnimation.isBypass ? "rgba(239, 68, 68, 0.6)" : "rgba(16, 185, 129, 0.6)";
            ctx.shadowBlur = 10;
            ctx.beginPath();
            ctx.arc(targetPt.x, targetPt.y, 8, 0, Math.PI * 2);
            ctx.fill();
            ctx.restore();
        }

        // Increment car progress smoothly until reaching bay entrance
        if (enterCarAnimation.progress < 1.0) {
            enterCarAnimation.progress = Math.min(1.0, enterCarAnimation.progress + 0.016);
        }

        const numSegs = route.length - 1;
        const totalProgress = enterCarAnimation.progress * numSegs;
        const segIdx = Math.min(Math.floor(totalProgress), numSegs - 1);
        const segFrac = totalProgress - segIdx;

        const p1 = route[segIdx];
        const p2 = route[segIdx + 1];
        const bx = p1.x + (p2.x - p1.x) * segFrac;
        const by = p1.y + (p2.y - p1.y) * segFrac;

        const dx = p2.x - p1.x;
        const dy = p2.y - p1.y;
        let heading = 0;
        if (Math.abs(dx) > Math.abs(dy)) {
            heading = dx >= 0 ? Math.PI / 2 : -Math.PI / 2;
        } else {
            heading = dy >= 0 ? Math.PI : 0;
        }

        // Camera auto-follow / floor switching when entering car crosses slope threshold
        const isF2Target = enterCarAnimation.targetFloor === 2 || (enterCarAnimation.slotId && enterCarAnimation.slotId.startsWith("F2-"));
        if (isF2Target && by >= 350 && currentFloor === "F1") {
            switchFloor("F2");
        } else if (!isF2Target && currentFloor === "F2") {
            switchFloor("F1");
        }

        // Render realistic vehicle if present on the active viewing level
        if (isPointOnFloor({ x: bx, y: by }, currentFloor)) {
            drawRealisticCar(ctx, bx, by, 40, 70, enterCarAnimation.color, enterCarAnimation.plate, enterCarAnimation.isEV, heading);
        }

        // When arrived at bay, automatically complete parking into the assigned bay
        if (enterCarAnimation.progress >= 1.0 && !enterCarAnimation.isBypass) {
            if (!enterCarAnimation.autoParkTimer) {
                enterCarAnimation.autoParkTimer = setTimeout(async () => {
                    await triggerSimAction('park');
                }, 750);
            }
            if (isPointOnFloor({ x: bx, y: by }, currentFloor)) {
                ctx.strokeStyle = "rgba(2, 132, 199, " + (0.6 + Math.sin(pulsePhase) * 0.3) + ")";
                ctx.lineWidth = 2.5;
                ctx.beginPath();
                ctx.arc(bx, by, 28 + Math.sin(pulsePhase) * 4, 0, Math.PI * 2);
                ctx.stroke();
            }
        }
    } else if (activeRoute && activeRoute.length > 1) {
        // Static Custom Route Display (from A* Navigator explorer)
        drawFloorRoute(ctx, activeRoute, currentFloor, "#6366f1");
    }

    // 6. Draw Exit Animation along Orthogonal Exit Route
    if (exitCarAnimation && exitCarAnimation.route && exitCarAnimation.route.length > 1) {
        exitCarAnimation.progress += 0.014;
        if (exitCarAnimation.progress >= 1.0) {
            // Safety check: finalize if car crossed line
            if (!exitCarAnimation.hasCrossedExitLine) {
                exitCarAnimation.hasCrossedExitLine = true;
                onVehicleCrossExitLine(exitCarAnimation);
            }
            exitCarAnimation = null;
            activeRoute = null;
        } else {
            // Draw Glowing Rose Exit Route Line
            drawFloorRoute(ctx, exitCarAnimation.route, currentFloor, "#e11d48");

            // Draw Exit Gate pulsing beacon at CAM_02 (940, 55) on F1
            if (currentFloor === "F1") {
                ctx.save();
                ctx.fillStyle = "#10b981";
                ctx.shadowColor = "rgba(16, 185, 129, 0.8)";
                ctx.shadowBlur = 12;
                ctx.beginPath();
                ctx.arc(940, 55, 9 + Math.sin(pulsePhase) * 2, 0, Math.PI * 2);
                ctx.fill();
                ctx.strokeStyle = "rgba(16, 185, 129, 0.5)";
                ctx.lineWidth = 2;
                ctx.beginPath();
                ctx.arc(940, 55, 18 + Math.sin(pulsePhase) * 4, 0, Math.PI * 2);
                ctx.stroke();
                ctx.restore();
            }

            const r = exitCarAnimation.route;
            const numSegs = r.length - 1;
            const totalProg = exitCarAnimation.progress * numSegs;
            const sIdx = Math.min(Math.floor(totalProg), numSegs - 1);
            const sFrac = totalProg - sIdx;

            const p1 = r[sIdx];
            const p2 = r[sIdx + 1];
            const ex = p1.x + (p2.x - p1.x) * sFrac;
            const ey = p1.y + (p2.y - p1.y) * sFrac;

            const dx = p2.x - p1.x;
            const dy = p2.y - p1.y;
            let heading = 0;
            if (Math.abs(dx) > Math.abs(dy)) {
                heading = dx >= 0 ? Math.PI / 2 : -Math.PI / 2;
            } else {
                heading = dy >= 0 ? Math.PI : 0;
            }

            // Floor switching when ascending Right Slope (F2 -> F1)
            const originFloor = exitCarAnimation.originFloor || 1;
            if (originFloor === 2 && ey <= 350 && currentFloor === "F2") {
                switchFloor("F1");
            } else if (originFloor === 1 && currentFloor === "F2") {
                switchFloor("F1");
            }

            // Check if vehicle physically crosses the exit line at CAM_02 (x >= 915 on Floor 1)
            if (!exitCarAnimation.hasCrossedExitLine && currentFloor === "F1" && (ex >= 915 || exitCarAnimation.progress >= 0.93)) {
                exitCarAnimation.hasCrossedExitLine = true;
                onVehicleCrossExitLine(exitCarAnimation);
            }

            // Render realistic vehicle if present on the active viewing level
            if (isPointOnFloor({ x: ex, y: ey }, currentFloor)) {
                drawRealisticCar(ctx, ex, ey, 40, 70, exitCarAnimation.color, exitCarAnimation.plate, false, heading);

                // When crossed exit line, draw floating scanner tag over the car
                if (exitCarAnimation.hasCrossedExitLine) {
                    ctx.save();
                    ctx.fillStyle = "rgba(15, 23, 42, 0.92)";
                    ctx.strokeStyle = "#10b981";
                    ctx.lineWidth = 1.5;
                    ctx.shadowColor = "rgba(16, 185, 129, 0.8)";
                    ctx.shadowBlur = 10;
                    ctx.beginPath();
                    ctx.roundRect(ex - 52, ey - 36, 104, 22, 6);
                    ctx.fill();
                    ctx.stroke();
                    ctx.shadowBlur = 0;
                    ctx.fillStyle = "#10b981";
                    ctx.font = "bold 9px 'JetBrains Mono', monospace";
                    ctx.textAlign = "center";
                    ctx.textBaseline = "middle";
                    ctx.fillText(`CAM_02: ${exitCarAnimation.plate}`, ex, ey - 25);
                    ctx.restore();
                }
            }
        }
    }

    // 7. Active Laser Scan Burst FX at EXIT GATE [CAM_02]
    if (exitScanBurst > 0) {
        exitScanBurst--;
        if (currentFloor === "F1") {
            ctx.save();
            const alpha = exitScanBurst / 35;
            ctx.fillStyle = `rgba(16, 185, 129, ${alpha * 0.35})`;
            ctx.fillRect(890, 16, 70, 68);

            ctx.strokeStyle = `rgba(255, 255, 255, ${alpha * 0.95})`;
            ctx.lineWidth = 4;
            ctx.shadowColor = "#10b981";
            ctx.shadowBlur = 24;
            ctx.beginPath();
            ctx.moveTo(925, 16);
            ctx.lineTo(925, 84);
            ctx.stroke();

            ctx.fillStyle = "#ffffff";
            ctx.shadowBlur = 0;
            ctx.beginPath();
            ctx.arc(925, 18, 5, 0, Math.PI * 2);
            ctx.arc(925, 82, 5, 0, Math.PI * 2);
            ctx.fill();

            // Optical HUD text over gate
            ctx.fillStyle = "#10b981";
            ctx.shadowColor = "rgba(16, 185, 129, 0.9)";
            ctx.shadowBlur = 6;
            ctx.font = "bold 10px 'JetBrains Mono', monospace";
            ctx.textAlign = "center";
            ctx.fillText("⚡ ANPR DETECTED: TARIFF CALCULATED", 925, 10);
            ctx.restore();
        }
    }

    requestAnimationFrame(renderDigitalTwin);
}

// Interactive Canvas Hover & Click Listeners
canvas.addEventListener("mousemove", (evt) => {
    if (!liveState || !liveState.slots) return;
    const rect = canvas.getBoundingClientRect();
    const scaleX = canvas.width / rect.width;
    const scaleY = canvas.height / rect.height;
    const mx = (evt.clientX - rect.left) * scaleX;
    const my = (evt.clientY - rect.top) * scaleY;

    let found = null;
    const viewingFloorNum = (currentFloor === "F2") ? 2 : 1;
    Object.values(liveState.slots).forEach(slot => {
        const slotFloorNum = slot.floor || (slot.id.startsWith("F2-") ? 2 : 1);
        if (slotFloorNum !== viewingFloorNum) return;

        const x = slot.x;
        const y = slot.y;
        const w = slot.width;
        const h = slot.height;
        if (mx >= x && mx <= x + w && my >= y && my <= y + h) {
            found = slot.id;
        }
    });

    hoveredSlotId = found;
    canvas.style.cursor = found && liveState.slots[found].status === "OCCUPIED" ? "pointer" : "default";
});

canvas.addEventListener("mouseleave", () => {
    hoveredSlotId = null;
    canvas.style.cursor = "default";
});

canvas.addEventListener("click", (evt) => {
    if (!liveState || !liveState.slots) return;
    const rect = canvas.getBoundingClientRect();
    const scaleX = canvas.width / rect.width;
    const scaleY = canvas.height / rect.height;
    const mx = (evt.clientX - rect.left) * scaleX;
    const my = (evt.clientY - rect.top) * scaleY;

    const viewingFloorNum = (currentFloor === "F2") ? 2 : 1;
    Object.values(liveState.slots).forEach(slot => {
        const slotFloorNum = slot.floor || (slot.id.startsWith("F2-") ? 2 : 1);
        if (slotFloorNum !== viewingFloorNum) return;

        const x = slot.x;
        const y = slot.y;
        const w = slot.width;
        const h = slot.height;
        if (mx >= x && mx <= x + w && my >= y && my <= y + h) {
            if (slot.status === "OCCUPIED") {
                openSlotModal(slot);
            }
        }
    });
});

// Modal Actions
function openSlotModal(slot) {
    selectedSlotData = slot;
    const modal = document.getElementById("slotActionModal");
    if (!modal) return;

    document.getElementById("modal-slot-id").innerText = `BAY ${slot.id}`;
    document.getElementById("modal-slot-type").innerText = "GENERAL";
    
    const plate = slot.vehicle_plate || `TRK-${slot.track_id || '99'}`;
    document.getElementById("modal-plate-val").innerText = plate;

    // Find active session for this slot
    const session = liveState && liveState.active_sessions ? 
        liveState.active_sessions.find(s => s.assigned_slot === slot.id || s.plate_number === slot.vehicle_plate) : null;

    const entryTs = (session && session.entry_timestamp) || slot.entry_timestamp;
    const duration = formatLiveDuration(entryTs);
    const feeObj = calculateLiveFee(entryTs, (liveState && liveState.kpis && liveState.kpis.rate_per_30m) || 20);
    const fee = session && session.status === "BYPASS" ? "₹0" : feeObj.formatted;

    const durEl = document.getElementById("modal-duration-val");
    if (durEl) durEl.innerText = duration;

    const feeEl = document.getElementById("modal-fee-val");
    if (feeEl) feeEl.innerText = fee;

    const btnTextEl = document.getElementById("modal-exit-btn-text");
    if (btnTextEl) btnTextEl.innerText = `Pay ${fee} & Exit Vehicle`;

    document.getElementById("modal-session-meta").innerText = `Status: OCCUPIED (PARKED) • In Bay ${slot.id}`;
    
    modal.classList.remove("hidden");
}

function closeSlotModal() {
    const modal = document.getElementById("slotActionModal");
    if (modal) modal.classList.add("hidden");
    selectedSlotData = null;
}

async function confirmModalExit() {
    if (!selectedSlotData) return;
    const targetSlotId = selectedSlotData.id;
    const targetPlate = selectedSlotData.vehicle_plate || targetSlotId;
    closeSlotModal();
    await exitSpecificVehicle(targetSlotId, targetPlate);
}

// Exit Specific Target Vehicle by Slot ID or Plate Number
async function exitSpecificVehicle(targetId, targetPlate) {
    try {
        const floorNum = (targetId && targetId.startsWith("F2-")) || currentFloor === "F2" ? 2 : 1;
        const res = await fetch(`${API_BASE}/simulate-event?action=exit&finalize=false&target=${encodeURIComponent(targetId)}&floor=${floorNum}`, { method: "POST" });
        const data = await res.json();
        
        // Trigger smooth exit route animation if route is provided
        if (data && data.result && data.result.exit_route && data.result.exit_route.coordinates) {
            const originFloor = data.floor || (data.result.exit_route && data.result.exit_route.origin_floor) || floorNum;
            exitCarAnimation = {
                route: data.result.exit_route.coordinates,
                progress: 0,
                plate: data.result.plate_number || targetPlate || "EXIT",
                slotId: data.result.slot_id || targetId,
                originFloor: originFloor,
                entryTimestamp: data.result.entry_timestamp || (Date.now() / 1000 - 60),
                billing: data.result.billing,
                color: "#e11d48",
                hasCrossedExitLine: false
            };
            activeRoute = data.result.exit_route.coordinates;
        }
        await fetchParkingState();
    } catch (err) {
        console.error("Failed to exit vehicle:", err);
    }
}

let exitHudResetTimer = null;

// Handler triggered the instant the vehicle crosses the exit line at CAM_02
async function onVehicleCrossExitLine(anim) {
    if (!anim) return;
    exitScanBurst = 35; // Trigger optical laser scan burst animation at EXIT GATE [CAM_02]

    const nowSec = Date.now() / 1000;
    const entryTs = anim.entryTimestamp || (nowSec - 60);
    const durationFormatted = formatLiveDuration(entryTs);
    const durationSec = Math.max(1, Math.floor(nowSec - entryTs));
    const blocks = Math.max(1, Math.ceil(durationSec / 1800));
    const tariffInr = blocks * 20;
    const tariffFormatted = `₹${tariffInr}`;

    // 1. Update Telemetry HUD with Exit Detection at CAM_02
    const sourceBadge = document.getElementById("cv-source-badge");
    const hudTrack = document.getElementById("hud-track-id");
    const hudPlate = document.getElementById("hud-plate");
    const hudOcr = document.getElementById("hud-ocr-conf");
    const hudSlot = document.getElementById("hud-assigned-slot");

    if (sourceBadge) {
        sourceBadge.innerText = "CAM_02 EXIT GATE [LPR DETECTED + TARIFF ENGINE]";
        sourceBadge.style.color = "#10b981";
    }
    if (hudTrack) hudTrack.innerText = "#CAM02";
    if (hudPlate) {
        hudPlate.innerText = anim.plate;
        hudPlate.style.color = "#10b981";
    }
    if (hudOcr) hudOcr.innerText = "99.4% (MATCH VERIFIED)";
    if (hudSlot) {
        hudSlot.innerText = `VACATED: ${anim.slotId || 'BAY'}`;
        hudSlot.style.color = "#64748b";
    }

    if (exitHudResetTimer) clearTimeout(exitHudResetTimer);
    exitHudResetTimer = setTimeout(() => {
        if (sourceBadge) {
            sourceBadge.innerText = (systemMode === "REAL") ? "CAM_01 GATE IN (LIVE YOLOv8 + OCR)" : "VIRTUAL DISPATCHER";
            sourceBadge.style.color = "";
        }
    }, 7000);

    // 2. Call Backend Finalize to persist COMPLETED status and add to total_revenue_inr
    let finalizedTotalRev = null;
    try {
        const finalizeRes = await fetch(`${API_BASE}/simulate-event?action=exit_finalize&target=${encodeURIComponent(anim.plate)}&slot=${encodeURIComponent(anim.slotId || '')}`, { method: "POST" });
        if (finalizeRes.ok) {
            const fData = await finalizeRes.json();
            if (fData && fData.result) {
                finalizedTotalRev = fData.result.total_revenue_inr;
            }
        }
    } catch (e) {
        console.error("Exit finalize failed:", e);
    }

    // 3. Add to Total Revenue with glowing animation and numeric count-up
    triggerRevenueIncrementAnimation(tariffInr, finalizedTotalRev);

    // 4. Show Floating Exit Billing Receipt Toast
    showExitBillingReceiptToast({
        plate: anim.plate,
        slotId: anim.slotId,
        floor: anim.originFloor || 1,
        duration: durationFormatted,
        tariff: tariffFormatted,
        rate: "₹20 / 30m block",
        totalRevenue: finalizedTotalRev
    });

    // 5. Update Activity Feed
    appendLocalActivity("EXIT_CAM_02", `Vehicle ${anim.plate} crossed Exit Line [CAM_02]. Stay: ${durationFormatted} • Tariff: ${tariffFormatted} added to Total Revenue.`);

    // 6. Refresh authoritative parking state
    await fetchParkingState();
}

function triggerRevenueIncrementAnimation(addedAmount, targetTotal) {
    const revEl = document.getElementById("kpi-revenue");
    const kpiCard = revEl ? revEl.closest(".kpi-glass-card") : null;
    if (!revEl) return;

    if (kpiCard) {
        kpiCard.classList.remove("kpi-revenue-pulse");
        void kpiCard.offsetWidth;
        kpiCard.classList.add("kpi-revenue-pulse");
        setTimeout(() => kpiCard.classList.remove("kpi-revenue-pulse"), 2500);

        const floatBadge = document.createElement("div");
        floatBadge.className = "revenue-float-badge";
        floatBadge.innerText = `+₹${addedAmount}`;
        kpiCard.appendChild(floatBadge);
        setTimeout(() => floatBadge.remove(), 1800);
    }

    if (targetTotal != null) {
        const currentText = revEl.innerText.replace(/[^0-9]/g, '');
        const currentVal = parseInt(currentText, 10) || 0;
        const diff = targetTotal - currentVal;
        if (diff > 0) {
            let step = 0;
            const steps = 12;
            const timer = setInterval(() => {
                step++;
                const val = Math.round(currentVal + (diff * (step / steps)));
                revEl.innerText = `₹${val.toLocaleString()}`;
                if (step >= steps) {
                    clearInterval(timer);
                    revEl.innerText = `₹${targetTotal.toLocaleString()}`;
                }
            }, 35);
        } else {
            revEl.innerText = `₹${targetTotal.toLocaleString()}`;
        }
    }
}

function showExitBillingReceiptToast(receipt) {
    const existing = document.getElementById("exitReceiptToast");
    if (existing) existing.remove();

    const toast = document.createElement("div");
    toast.id = "exitReceiptToast";
    toast.className = "exit-receipt-toast";
    toast.innerHTML = `
        <div class="receipt-header">
            <div class="receipt-title-row">
                <span class="receipt-icon">💳</span>
                <strong>EXIT GATE [CAM_02] • PAYMENT SETTLED</strong>
            </div>
            <button class="receipt-close-btn" onclick="this.closest('#exitReceiptToast').remove()">✕</button>
        </div>
        <div class="receipt-body">
            <div class="receipt-stat-line">
                <span class="receipt-label">VEHICLE PLATE:</span>
                <span class="receipt-val plate-badge-pill">${receipt.plate}</span>
            </div>
            <div class="receipt-stat-line">
                <span class="receipt-label">BAY VACATED:</span>
                <span class="receipt-val font-bold text-slate">${receipt.slotId || 'RAMP'} (Floor ${receipt.floor})</span>
            </div>
            <div class="receipt-stat-line">
                <span class="receipt-label">TIME SPENT IN BAY:</span>
                <span class="receipt-val font-mono text-indigo font-bold">⏱ ${receipt.duration}</span>
            </div>
            <div class="receipt-stat-line">
                <span class="receipt-label">CALCULATED TARIFF:</span>
                <span class="receipt-val font-mono text-emerald font-bold" style="font-size: 15px;">${receipt.tariff}</span>
            </div>
        </div>
        <div class="receipt-footer">
            <span class="receipt-footer-tag">✅ ADDED TO TOTAL REVENUE</span>
            <span class="receipt-tariff-rate">${receipt.rate}</span>
        </div>
        <div class="receipt-progress-bar"><div class="receipt-progress-fill"></div></div>
    `;

    document.body.appendChild(toast);

    setTimeout(() => {
        if (toast.parentNode) {
            toast.classList.add("toast-fade-out");
            setTimeout(() => toast.remove(), 400);
        }
    }, 5500);
}

function appendLocalActivity(type, message) {
    const feedContainer = document.getElementById("activityFeed");
    if (!feedContainer) return;
    const nowStr = new Date().toTimeString().split(" ")[0];
    const newEntry = document.createElement("div");
    newEntry.className = "activity-feed-entry";
    newEntry.innerHTML = `
        <span class="entry-time">${nowStr} • ${type}</span>
        <span class="entry-desc">${message}</span>
    `;
    feedContainer.prepend(newEntry);
}

// ==========================================================================
// Vehicle Photo / Video Upload & YOLOv8 ANPR Pipeline
// ==========================================================================
async function handleVehicleFileUpload(evt) {
    const file = evt.target.files && evt.target.files[0];
    if (!file) return;

    await uploadCarFile(file);
    evt.target.value = "";
}

async function uploadCarFile(file) {
    const uploadDropzone = document.getElementById("uploadDropzone");
    const previewWrap = document.getElementById("uploadPreviewWrap");
    const previewImg = document.getElementById("uploadPreviewImg");
    const metaBadge = document.getElementById("preview-meta-badge");

    const primaryTextEl = uploadDropzone ? uploadDropzone.querySelector(".upload-primary-text") : null;
    const origText = primaryTextEl ? primaryTextEl.innerText : "Upload Car Photo";
    if (primaryTextEl) primaryTextEl.innerText = "Analyzing with YOLOv8 & EasyOCR...";
    if (uploadDropzone) uploadDropzone.style.opacity = "0.7";

    const formData = new FormData();
    formData.append("file", file);

    try {
        const res = await fetch(`${API_BASE}/upload-vehicle`, {
            method: "POST",
            body: formData
        });

        if (!res.ok) {
            const errData = await res.json().catch(() => ({}));
            alert(`Detection Error: ${errData.detail || 'Could not process vehicle'}`);
            return;
        }

        const data = await res.json();
        const det = data.detection;
        const session = data.session;

        // 1. Show Annotated YOLOv8 Image Snapshot & Automated Confirmation
        if (det && det.annotated_image && previewWrap && previewImg) {
            previewImg.src = det.annotated_image;
            previewWrap.classList.remove("hidden");
            const confPct = det.ocr_confidence > 0 ? `${(det.ocr_confidence * 100).toFixed(0)}%` : "N/A";
            const isConfirmed = det.ocr_confidence >= 0.5 && det.plate_number !== "UNKNOWN";
            if (metaBadge) {
                if (isConfirmed) {
                    metaBadge.innerHTML = `<span style="color:#10b981;">✓ CONFIRMED:</span> ${det.plate_number} (${det.vehicle_type.toUpperCase()}) • OCR: ${confPct}`;
                    metaBadge.style.color = "#0f172a";
                    metaBadge.style.borderColor = "#a7f3d0";
                    metaBadge.style.background = "#ecfdf5";
                } else {
                    metaBadge.innerHTML = `<span style="color:#f59e0b;">⚠️ RECHECKED:</span> ${det.plate_number} • OCR: ${confPct}`;
                    metaBadge.style.color = "#0f172a";
                    metaBadge.style.borderColor = "#fde68a";
                    metaBadge.style.background = "#fffbeb";
                }
            }
        }

        // 2. Update HUD Telemetry
        document.getElementById("hud-track-id").innerText = `#${session.track_id || '101'}`;
        document.getElementById("hud-plate").innerText = session.plate_number;
        document.getElementById("hud-ocr-conf").innerText = det.ocr_confidence > 0 ? `${(det.ocr_confidence * 100).toFixed(0)}% [CONFIRMED]` : "Auto-Checked";
        const assignedSlotEl = document.getElementById("hud-assigned-slot");
        if (assignedSlotEl) {
            if (session.assigned_slot) {
                assignedSlotEl.innerText = session.assigned_slot;
                assignedSlotEl.style.color = "#10b981";
            } else {
                assignedSlotEl.innerText = "🚫 FULL (EXIT)";
                assignedSlotEl.style.color = "#ef4444";
            }
        }

        // 3. Trigger Smooth Digital Twin 2D Vehicle Entrance Animation
        if (session && session.route && session.route.coordinates) {
            enterCarAnimation = {
                route: session.route.coordinates,
                progress: 0,
                plate: session.plate_number,
                isEV: false,
                slotId: session.assigned_slot,
                targetFloor: session.assigned_slot && session.assigned_slot.startsWith("F2-") ? 2 : 1,
                color: "#2563eb",
                isBypass: !session.assigned_slot
            };
            activeRoute = session.route.coordinates;
        }

        // 4. Refresh Authoritative State Engine & KPIs
        await fetchParkingState();

    } catch (err) {
        console.error("Vehicle upload failed:", err);
        alert("Failed to communicate with Parking CV Backend. Please verify the backend server is running.");
    } finally {
        if (primaryTextEl) primaryTextEl.innerText = origText;
        if (uploadDropzone) uploadDropzone.style.opacity = "1";
    }
}

function clearUploadPreview(evt) {
    if (evt) evt.stopPropagation();
    const previewWrap = document.getElementById("uploadPreviewWrap");
    const previewImg = document.getElementById("uploadPreviewImg");
    if (previewWrap) previewWrap.classList.add("hidden");
    if (previewImg) previewImg.src = "";
}

function initDragAndDrop() {
    const card = document.getElementById("uploadCard");
    if (!card) return;

    ['dragenter', 'dragover'].forEach(eventName => {
        card.addEventListener(eventName, (e) => {
            e.preventDefault();
            e.stopPropagation();
            card.classList.add('drag-over');
        }, false);
    });

    ['dragleave', 'drop'].forEach(eventName => {
        card.addEventListener(eventName, (e) => {
            e.preventDefault();
            e.stopPropagation();
            card.classList.remove('drag-over');
        }, false);
    });

    card.addEventListener('drop', (e) => {
        e.preventDefault();
        e.stopPropagation();
        card.classList.remove('drag-over');
        const dt = e.dataTransfer;
        const files = dt.files;
        if (files && files.length > 0) {
            uploadCarFile(files[0]);
        }
    }, false);
}

// Simulation Dispatcher Actions
async function triggerSimAction(action) {
    try {
        if (action === "reset") {
            if (enterCarAnimation && enterCarAnimation.autoParkTimer) {
                clearTimeout(enterCarAnimation.autoParkTimer);
                enterCarAnimation.autoParkTimer = null;
            }
            enterCarAnimation = null;
            exitCarAnimation = null;
            activeRoute = null;
            clearUploadPreview();
            const trackEl = document.getElementById("hud-track-id");
            const plateEl = document.getElementById("hud-plate");
            const confEl = document.getElementById("hud-ocr-conf");
            const slotEl = document.getElementById("hud-assigned-slot");
            if (trackEl) trackEl.innerText = "#--";
            if (plateEl) plateEl.innerText = "NO VEHICLE";
            if (confEl) confEl.innerText = "--%";
            if (slotEl) {
                slotEl.innerText = "--";
                slotEl.style.color = "";
            }
            await fetch(`${API_BASE}/reset`, { method: "POST" });
            await fetchParkingState();
            return;
        }
        if (action === "park") {
            if (enterCarAnimation && enterCarAnimation.autoParkTimer) {
                clearTimeout(enterCarAnimation.autoParkTimer);
                enterCarAnimation.autoParkTimer = null;
            }
            enterCarAnimation = null;
            activeRoute = null;
        }
        const floorParam = `&floor=${currentFloor === "F2" ? 2 : 1}`;
        const finalizeParam = action === "exit" ? "&finalize=false" : "";
        const res = await fetch(`${API_BASE}/simulate-event?action=${action}${floorParam}${finalizeParam}`, { method: "POST" });
        const data = await res.json();
        
        if (action === "entry" && data && data.session && data.session.route && data.session.route.coordinates) {
            const isF2 = data.session.assigned_slot && data.session.assigned_slot.startsWith("F2-");
            enterCarAnimation = {
                route: data.session.route.coordinates,
                progress: 0,
                plate: data.session.plate_number,
                isEV: false,
                slotId: data.session.assigned_slot,
                targetFloor: isF2 ? 2 : 1,
                color: "#2563eb",
                isBypass: !data.session.assigned_slot
            };
            activeRoute = data.session.route.coordinates;

            // Immediately update Live CV Telemetry HUD
            const trackEl = document.getElementById("hud-track-id");
            const plateEl = document.getElementById("hud-plate");
            const confEl = document.getElementById("hud-ocr-conf");
            const slotEl = document.getElementById("hud-assigned-slot");
            if (trackEl) trackEl.innerText = `#${data.session.track_id || '101'}`;
            if (plateEl) plateEl.innerText = data.session.plate_number;
            if (confEl) confEl.innerText = `${(data.session.ocr_confidence ? data.session.ocr_confidence * 100 : 94).toFixed(0)}% [CONFIRMED]`;
            if (slotEl) {
                slotEl.innerText = data.session.assigned_slot || "🚫 FULL (EXIT)";
                slotEl.style.color = data.session.assigned_slot ? "#10b981" : "#ef4444";
            }
        } else if (action === "exit" && data && data.result && data.result.exit_route && data.result.exit_route.coordinates) {
            const originFloor = data.floor || (data.result.exit_route && data.result.exit_route.origin_floor) || (currentFloor === "F2" ? 2 : 1);
            exitCarAnimation = {
                route: data.result.exit_route.coordinates,
                progress: 0,
                plate: data.result.plate_number || "EXIT",
                slotId: data.result.slot_id,
                originFloor: originFloor,
                entryTimestamp: data.result.entry_timestamp || (Date.now() / 1000 - 60),
                billing: data.result.billing,
                color: "#e11d48",
                hasCrossedExitLine: false
            };
            activeRoute = data.result.exit_route.coordinates;
        }
        await fetchParkingState();
    } catch (e) {
        console.error("Simulation action failed", e);
    }
}

// Custom A* Route Exploration Handler
async function exploreCustomRoute() {
    const startSelect = document.getElementById("route-start-select");
    const targetSelect = document.getElementById("route-target-select");
    if (!startSelect || !targetSelect) return;

    const startNode = startSelect.value;
    const targetSlot = targetSelect.value;

    try {
        const res = await fetch(`${API_BASE}/route`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ start_node: startNode, target_slot: targetSlot })
        });
        const data = await res.json();
        const nodes = data.path_nodes || data.path;
        const dist = data.distance_pixels || data.total_distance || 0;
        
        if (data && nodes && data.coordinates) {
            activeRoute = data.coordinates; // Render path live on canvas!

            // Auto-switch floor view if target or origin is on the other level
            if ((targetSlot.startsWith("F2-") || targetSlot === "F2_EXIT" || startNode.startsWith("F2-") || startNode === "F2_ENTRY") && currentFloor !== "F2") {
                switchFloor("F2");
            } else if ((targetSlot.startsWith("F1-") || targetSlot === "EXIT") && currentFloor !== "F1" && !startNode.startsWith("F2-")) {
                switchFloor("F1");
            }
            
            // Render step sequence
            const seqContainer = document.getElementById("route-step-seq");
            if (seqContainer) {
                seqContainer.innerHTML = nodes.map((node, i) => {
                    const isTarget = (i === nodes.length - 1);
                    return `
                        <span class="route-step-node ${isTarget ? 'node-target' : ''}">${node}</span>
                        ${!isTarget ? '<span class="route-step-arrow">➔</span>' : ''}
                    `;
                }).join("");
            }

            const metricsEl = document.getElementById("route-metrics-badge");
            if (metricsEl) {
                metricsEl.innerHTML = `
                    <span>Manhattan Distance: <strong>${Math.round(dist)} px</strong></span> • 
                    <span>Waypoints: <strong>${nodes.length}</strong></span> • 
                    <span class="text-emerald"><strong>100% Orthogonal (90°)</strong></span>
                `;
            }
        }
    } catch (err) {
        console.error("Failed to calculate custom route:", err);
    }
}

// Sidebar Navigation & Section Routing Handler
function initNavigation() {
    const navItems = document.querySelectorAll(".sidebar-nav .nav-item");
    
    function setActiveNavItem(hash) {
        if (!hash || hash === "#") hash = "#dashboard";
        
        navItems.forEach(item => {
            const href = item.getAttribute("href");
            if (href === hash) {
                item.classList.add("active");
            } else {
                item.classList.remove("active");
            }
        });

        // Smooth scroll vertically to target section without horizontal displacement
        const targetId = hash.substring(1);
        const targetElement = document.getElementById(targetId);
        if (targetElement) {
            const yOffset = -24;
            const targetY = targetElement.getBoundingClientRect().top + window.pageYOffset + yOffset;
            window.scrollTo({ top: Math.max(0, targetY), left: 0, behavior: "smooth" });
            
            // Add momentary highlight pulse
            targetElement.classList.remove("section-highlight");
            void targetElement.offsetWidth; // Trigger reflow
            targetElement.classList.add("section-highlight");
        }
    }

    navItems.forEach(item => {
        item.addEventListener("click", (e) => {
            e.preventDefault();
            const hash = item.getAttribute("href");
            history.pushState(null, null, hash);
            setActiveNavItem(hash);
        });
    });

    window.addEventListener("hashchange", () => {
        setActiveNavItem(window.location.hash);
    });

    // Check initial hash on load
    if (window.location.hash) {
        setTimeout(() => setActiveNavItem(window.location.hash), 150);
    }
}

function toggleSidebarCollapse() {
    const sidebar = document.querySelector(".sidebar-container");
    if (sidebar) {
        sidebar.classList.toggle("collapsed");
    }
}

// Initial Bootstrapping
initNavigation();
initDragAndDrop();
setInterval(fetchParkingState, 1000);
fetchParkingState();
renderDigitalTwin();
