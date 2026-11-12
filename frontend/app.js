// PARKIQ Intelligent Parking Control Center - Digital Twin & Telemetry Engine
const API_BASE = "http://localhost:8000/api";

let systemMode = "REAL"; // REAL vs SIMULATION
let currentFloor = "F1"; // "F1" (First Floor) vs "F2" (Second Floor)
let liveState = null;
let activeRoute = null; // static / custom A* coordinate path
let enterCarAnimation = null; // smooth single-pass entering route animation
let exitCarAnimation = null; // smooth exit route animation
let pulsePhase = 0;

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

// Live Clock
function updateClock() {
    const now = new Date();
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

// ==========================================================================
// Ultra-Realistic Top-Down Vector Car Drawing Routine
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

    // 1. Soft Shadow
    ctx.shadowColor = "rgba(15, 23, 42, 0.25)";
    ctx.shadowBlur = 12;
    ctx.shadowOffsetY = 4;

    // 2. Wheels / Tires (4 Corner Black Wheels with Rims)
    ctx.fillStyle = "#1e293b";
    const tireW = 8;
    const tireH = 18;
    // Front Left & Right Tires
    ctx.fillRect(-w/2 - 3, -h/2 + 12, tireW, tireH);
    ctx.fillRect(w/2 - 5, -h/2 + 12, tireW, tireH);
    // Rear Left & Right Tires
    ctx.fillRect(-w/2 - 3, h/2 - 30, tireW, tireH);
    ctx.fillRect(w/2 - 5, h/2 - 30, tireW, tireH);

    // 3. Side Wing Mirrors
    ctx.fillStyle = primaryColor || "#0284c7";
    ctx.beginPath();
    ctx.roundRect(-w/2 - 5, -h/2 + 24, 6, 8, 2);
    ctx.roundRect(w/2 - 1, -h/2 + 24, 6, 8, 2);
    ctx.fill();

    // 4. Main Metallic Car Body with Gradient
    const bodyGrad = ctx.createLinearGradient(-w/2, -h/2, w/2, h/2);
    bodyGrad.addColorStop(0, primaryColor || "#0284c7");
    bodyGrad.addColorStop(0.5, "#ffffff");
    bodyGrad.addColorStop(1, primaryColor || "#0369a1");

    ctx.fillStyle = bodyGrad;
    ctx.strokeStyle = "rgba(255, 255, 255, 0.8)";
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.roundRect(-w/2, -h/2, w, h, radius);
    ctx.fill();
    ctx.stroke();

    // Reset shadow
    ctx.shadowBlur = 0;
    ctx.shadowOffsetY = 0;

    // 5. Front Headlights (Glow White/Amber)
    ctx.fillStyle = "#fef08a";
    ctx.beginPath();
    ctx.roundRect(-w/2 + 4, -h/2 + 2, 10, 5, 2);
    ctx.roundRect(w/2 - 14, -h/2 + 2, 10, 5, 2);
    ctx.fill();

    // 6. Rear Tail Lights (Ruby Red)
    ctx.fillStyle = "#ef4444";
    ctx.beginPath();
    ctx.roundRect(-w/2 + 4, h/2 - 6, 12, 4, 2);
    ctx.roundRect(w/2 - 16, h/2 - 6, 12, 4, 2);
    ctx.fill();

    // 7. Front Windshield (Dark Glass with Glare Reflection)
    const glassGrad = ctx.createLinearGradient(0, -h/2 + 14, 0, -h/2 + 32);
    glassGrad.addColorStop(0, "#0f172a");
    glassGrad.addColorStop(0.7, "#1e293b");
    glassGrad.addColorStop(1, "#334155");

    ctx.fillStyle = glassGrad;
    ctx.beginPath();
    ctx.roundRect(-w/2 + 6, -h/2 + 14, w - 12, 18, [6, 6, 2, 2]);
    ctx.fill();

    // Glare line
    ctx.strokeStyle = "rgba(255, 255, 255, 0.35)";
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.moveTo(-w/2 + 10, -h/2 + 18);
    ctx.lineTo(w/2 - 16, -h/2 + 28);
    ctx.stroke();

    // 8. Rear Windshield
    ctx.fillStyle = glassGrad;
    ctx.beginPath();
    ctx.roundRect(-w/2 + 7, h/2 - 32, w - 14, 14, [2, 2, 6, 6]);
    ctx.fill();

    // 9. Roof Cabin with Sunroof / Panels
    ctx.fillStyle = "rgba(0, 0, 0, 0.08)";
    ctx.beginPath();
    ctx.roundRect(-w/2 + 9, -h/2 + 34, w - 18, h - 68, 4);
    ctx.fill();

    // 10. License Plate Badge at Rear
    if (plateText) {
        const plateW = Math.min(w - 12, 54);
        const plateH = 14;
        const plateY = h/2 - 16;

        ctx.fillStyle = "#ffffff";
        ctx.strokeStyle = "#0f172a";
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.roundRect(-plateW/2, plateY, plateW, plateH, 3);
        ctx.fill();
        ctx.stroke();

        ctx.fillStyle = "#0f172a";
        ctx.font = "bold 8px 'JetBrains Mono', monospace";
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText(plateText, 0, plateY + plateH/2);
    }

    ctx.restore();
}

// ==========================================================================
// Hazard Striping & Multi-Floor Slope Ramp Renderers
// ==========================================================================
function drawHazardStripes(ctx, x, y, width, height, stripeWidth = 5) {
    ctx.save();
    ctx.beginPath();
    ctx.rect(x, y, width, height);
    ctx.clip();

    // Safety Amber / Yellow
    ctx.fillStyle = "#facc15";
    ctx.fillRect(x, y, width, height);

    // Diagonal slate / black hazard stripes
    ctx.fillStyle = "#1e293b";
    const step = stripeWidth * 2;
    for (let offset = -height; offset < width + height; offset += step) {
        ctx.beginPath();
        ctx.moveTo(x + offset, y);
        ctx.lineTo(x + offset + stripeWidth, y);
        ctx.lineTo(x + offset + stripeWidth - height, y + height);
        ctx.lineTo(x + offset - height, y + height);
        ctx.closePath();
        ctx.fill();
    }
    ctx.restore();
}

function drawSlopeRamps(ctx, floor) {
    const isF1 = (floor === "F1");

    if (isF1) {
        // =====================================================================
        // FLOOR 1 SLOPE BARS (Exact Architectural Match to Floor 1 Blueprint)
        // =====================================================================
        const yStart = 85;
        const yEnd = 705;
        const rampHeight = yEnd - yStart;
        const barWidth = 50;

        // 1. LEFT SLOPE BAR (West Edge, Downward Traffic to F2)
        const leftX = 10;
        ctx.fillStyle = "#591319";
        ctx.fillRect(leftX, yStart, barWidth, rampHeight);
        ctx.strokeStyle = "#781d22";
        ctx.lineWidth = 1.5;
        ctx.strokeRect(leftX, yStart, barWidth, rampHeight);

        // White downward arrows (↓)
        ctx.fillStyle = "rgba(255, 255, 255, 0.9)";
        ctx.font = "bold 16px sans-serif";
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        const downArrowYs = [135, 195, 495, 565, 635];
        downArrowYs.forEach(ay => {
            ctx.fillText("↓", leftX + barWidth / 2, ay);
        });

        // Inward Arrow (➔) toward entry
        ctx.fillText("➔", leftX + barWidth / 2, 255);

        // Bold Rotated "SLOPE" text (reading downwards top-to-bottom)
        ctx.save();
        ctx.translate(leftX + barWidth / 2, 370);
        ctx.rotate(Math.PI / 2);
        ctx.fillStyle = "#ffffff";
        ctx.font = "bold 18px 'Plus Jakarta Sans', sans-serif";
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText("SLOPE", 0, 0);
        ctx.restore();

        // 2. RIGHT SLOPE BAR (East Edge, Upward Traffic from F2)
        const rightX = 900;
        ctx.fillStyle = "#591319";
        ctx.fillRect(rightX, yStart, barWidth, rampHeight);
        ctx.strokeStyle = "#781d22";
        ctx.lineWidth = 1.5;
        ctx.strokeRect(rightX, yStart, barWidth, rampHeight);

        // White upward arrows (↑)
        const upArrowYs = [135, 195, 255, 565, 635];
        upArrowYs.forEach(ay => {
            ctx.fillText("↑", rightX + barWidth / 2, ay);
        });

        // Inward Arrow (⬅) from aisle
        ctx.fillText("⬅", rightX + barWidth / 2, 495);

        // Bold Rotated "SLOPE" text (reading upwards bottom-to-top)
        ctx.save();
        ctx.translate(rightX + barWidth / 2, 370);
        ctx.rotate(-Math.PI / 2);
        ctx.fillStyle = "#ffffff";
        ctx.font = "bold 18px 'Plus Jakarta Sans', sans-serif";
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText("SLOPE", 0, 0);
        ctx.restore();

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

    segments.forEach(seg => {
        if (seg.length < 1) return;

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
        // FIRST FLOOR (F1) ARCHITECTURAL LAYOUT (6 SPACIOUS SLOTS LAYOUT)
        // =====================================================================

        // Top Entry / Exit Highway: x = 0 to 960, y = 15 to 85 (height = 70)
        ctx.fillRect(0, 15, 960, 70);

        // Aisle 1 (Southbound): x = 292 to 372 (width = 80, center = 332)
        ctx.fillRect(292, 85, 80, 555);

        // Aisle 2 (Northbound toward Exit): x = 588 to 668 (width = 80, center = 628)
        ctx.fillRect(588, 85, 80, 555);

        // Bottom Connector Road: x = 292 to 668, y = 640 to 705 (height = 65)
        ctx.fillRect(292, 640, 376, 65);

        // Roadway Curbs & Perimeter Markings
        ctx.strokeStyle = "#cbd5e1";
        ctx.lineWidth = 2;
        ctx.beginPath();
        // Top highway curbs
        ctx.moveTo(0, 15);
        ctx.lineTo(960, 15);
        ctx.moveTo(0, 85);
        ctx.lineTo(960, 85);
        ctx.stroke();

        // Dashed White Lane Centerlines
        ctx.strokeStyle = "#ffffff";
        ctx.setLineDash([12, 10]);
        ctx.lineWidth = 2.5;

        // Top Highway Centerline
        ctx.beginPath();
        ctx.moveTo(0, 50);
        ctx.lineTo(960, 50);
        ctx.stroke();

        // Aisle 1 Centerline (Southbound)
        ctx.beginPath();
        ctx.moveTo(332, 85);
        ctx.lineTo(332, 640);
        ctx.stroke();

        // Aisle 2 Centerline (Northbound)
        ctx.beginPath();
        ctx.moveTo(628, 85);
        ctx.lineTo(628, 640);
        ctx.stroke();

        // Bottom Connector Road Centerline (Eastbound)
        ctx.beginPath();
        ctx.moveTo(332, 672);
        ctx.lineTo(628, 672);
        ctx.stroke();
        ctx.setLineDash([]);

        // Directional Driving Arrows
        ctx.fillStyle = "rgba(100, 116, 139, 0.75)";
        ctx.font = "bold 15px sans-serif";
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";

        // Top Highway Eastbound Arrows
        ctx.fillText("➔", 160, 50);
        ctx.fillText("➔", 332, 50);
        ctx.fillText("➔", 480, 50);
        ctx.fillText("➔", 628, 50);
        ctx.fillText("➔", 800, 50);

        // Aisle 1 Southbound Arrows (↓)
        ctx.fillText("⬇", 332, 220);
        ctx.fillText("⬇", 332, 410);

        // Aisle 2 Northbound Arrows (↑)
        ctx.fillText("⬆", 628, 410);
        ctx.fillText("⬆", 628, 220);

        // Bottom Connector Road Eastbound Arrow (➔)
        ctx.fillText("➔", 480, 672);

        // Gate Badges
        ctx.fillStyle = "#0284c7";
        ctx.font = "bold 11px 'JetBrains Mono', monospace";
        ctx.textAlign = "left";
        ctx.textBaseline = "alphabetic";
        ctx.fillText("▶ ENTRY GATE [CAM_01]", 15, 12);

        ctx.fillStyle = "#10b981";
        ctx.textAlign = "right";
        ctx.fillText("EXIT GATE [CAM_02] ◀", 945, 12);

        // Blueprint Header Banner for F1
        ctx.save();
        ctx.fillStyle = "#1e3a8a";
        ctx.beginPath();
        ctx.roundRect(355, 1, 250, 16, 4);
        ctx.fill();
        ctx.fillStyle = "#ffffff";
        ctx.font = "bold 10px 'Plus Jakarta Sans', sans-serif";
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText("First floor  —  PARKING LAYOUT", 480, 9);
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
                // FLOOR 1: 6 SPACIOUS CARDS (Matching Floor 1 Blueprint Design)
                // =============================================================
                const slotNum = slot.bay_code || slot.id.replace("F1-S0", "").replace("F1-S", "");
                const isAmber = (slot.id === "F1-S03" || slot.id === "F1-S05");
                const isHorizontal = (slot.id === "F1-S03" || slot.id === "F1-S04");

                // Card Background & Border
                let bgFill, borderColor;
                if (isAmber) {
                    bgFill = isHovered ? "rgba(254, 237, 213, 0.98)" : "rgba(254, 243, 226, 0.95)";
                    borderColor = isHovered ? "#d97706" : "#f59e0b";
                } else {
                    bgFill = isHovered ? "rgba(209, 250, 229, 0.98)" : "rgba(220, 246, 233, 0.95)";
                    borderColor = isHovered ? "#059669" : "#34d399";
                }

                if (isAllocated) {
                    borderColor = "#0284c7";
                }

                ctx.save();
                ctx.beginPath();
                ctx.roundRect(x, y, w, h, 14);
                ctx.fillStyle = bgFill;
                ctx.fill();
                ctx.strokeStyle = borderColor;
                ctx.lineWidth = isHovered || isAllocated ? 3 : 2;
                if (isAllocated) {
                    ctx.setLineDash([7, 5]);
                }
                ctx.stroke();
                ctx.setLineDash([]);
                ctx.restore();

                // Large Bold Slot Number (e.g. 1, 2, 3, 4, 5, 6)
                ctx.save();
                ctx.fillStyle = "#0f172a";
                ctx.font = "bold 44px 'Plus Jakarta Sans', sans-serif";
                ctx.textAlign = "center";
                ctx.textBaseline = "middle";
                ctx.fillText(slotNum, x + 48, y + 100);

                // Status Pill Badge (Directly below the number)
                const pillW = 74;
                const pillH = 22;
                const pillX = (x + 48) - pillW / 2;
                const pillY = (y + 140) - pillH / 2;

                ctx.beginPath();
                ctx.roundRect(pillX, pillY, pillW, pillH, 11);

                if (isOccupied) {
                    ctx.fillStyle = "#831818"; // Rich dark maroon
                    ctx.fill();
                    ctx.fillStyle = "#ffffff";
                    ctx.font = "bold 10px 'Plus Jakarta Sans', sans-serif";
                    ctx.fillText("OCCUPIED", x + 48, y + 140);
                } else if (isAllocated) {
                    ctx.fillStyle = "#0284c7"; // Sky Blue
                    ctx.fill();
                    ctx.fillStyle = "#ffffff";
                    ctx.font = "bold 9.5px 'Plus Jakarta Sans', sans-serif";
                    ctx.fillText("INCOMING", x + 48, y + 140);
                    // Plate text below pill
                    ctx.fillStyle = "#0369a1";
                    ctx.font = "bold 9px 'JetBrains Mono', monospace";
                    ctx.fillText(slot.vehicle_plate || "ASSIGNED", x + 48, y + 158);
                } else {
                    ctx.fillStyle = "#059669"; // Emerald Green
                    ctx.fill();
                    ctx.fillStyle = "#ffffff";
                    ctx.font = "bold 10px 'Plus Jakarta Sans', sans-serif";
                    ctx.fillText("FREE", x + 48, y + 140);
                }
                ctx.restore();

                // Draw Realistic Parked Car
                if (isOccupied) {
                    const defaultPalette = {
                        "F1-S01": "#38bdf8",
                        "F1-S02": "#d97706",
                        "F1-S03": "#ea580c",
                        "F1-S04": "#94a3b8",
                        "F1-S05": "#334155",
                        "F1-S06": "#8b5cf6"
                    };
                    const carColor = defaultPalette[slot.id] || colorsPool[index % colorsPool.length];
                    const plate = slot.vehicle_plate || `S0${slotNum}`;

                    if (isHorizontal) {
                        const carX = x + 142;
                        const carY = y + 122;
                        drawRealisticCar(ctx, carX, carY, 48, 94, carColor, plate, slot.is_ev, Math.PI / 2);
                    } else {
                        const carX = x + 146;
                        const carY = y + 122;
                        drawRealisticCar(ctx, carX, carY, 48, 94, carColor, plate, slot.is_ev, 0);
                    }

                    // Hover action pill
                    if (isHovered) {
                        ctx.save();
                        ctx.fillStyle = "#e11d48";
                        ctx.shadowColor = "rgba(225, 29, 72, 0.4)";
                        ctx.shadowBlur = 8;
                        ctx.beginPath();
                        ctx.roundRect(x + w / 2 - 45, y + h - 28, 90, 20, 6);
                        ctx.fill();
                        ctx.shadowBlur = 0;
                        ctx.fillStyle = "#ffffff";
                        ctx.font = "bold 9px 'JetBrains Mono', monospace";
                        ctx.textAlign = "center";
                        ctx.textBaseline = "middle";
                        ctx.fillText("➔ CLICK TO EXIT", x + w / 2, y + h - 18);
                        ctx.restore();
                    }
                }
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
        exitCarAnimation.progress += 0.016;
        if (exitCarAnimation.progress >= 1.0) {
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

            // Render realistic vehicle if present on the active viewing level
            if (isPointOnFloor({ x: ex, y: ey }, currentFloor)) {
                drawRealisticCar(ctx, ex, ey, 40, 70, exitCarAnimation.color, exitCarAnimation.plate, false, heading);
            }
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
        const res = await fetch(`${API_BASE}/simulate-event?action=exit&target=${encodeURIComponent(targetId)}&floor=${floorNum}`, { method: "POST" });
        const data = await res.json();
        
        // Trigger smooth exit route animation if route is provided
        if (data && data.result && data.result.exit_route && data.result.exit_route.coordinates) {
            const originFloor = data.floor || (data.result.exit_route && data.result.exit_route.origin_floor) || floorNum;
            exitCarAnimation = {
                route: data.result.exit_route.coordinates,
                progress: 0,
                plate: data.result.plate_number || targetPlate || "EXIT",
                originFloor: originFloor,
                color: "#e11d48"
            };
            activeRoute = data.result.exit_route.coordinates;
        }
        await fetchParkingState();
    } catch (err) {
        console.error("Failed to exit vehicle:", err);
    }
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
        const res = await fetch(`${API_BASE}/simulate-event?action=${action}${floorParam}`, { method: "POST" });
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
        } else if (action === "exit" && data && data.result && data.result.exit_route && data.result.exit_route.coordinates) {
            const originFloor = data.floor || (data.result.exit_route && data.result.exit_route.origin_floor) || (currentFloor === "F2" ? 2 : 1);
            exitCarAnimation = {
                route: data.result.exit_route.coordinates,
                progress: 0,
                plate: data.result.plate_number || "EXIT",
                originFloor: originFloor,
                color: "#e11d48"
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
