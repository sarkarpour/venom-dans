/**
 * FerroWidget Android WebGL 2.0 Visualizer
 * Photorealistic dancing ferrofluid desktop & mobile visualizer
 * Includes:
 *  - 240/120 Hz fixed-substep semi-implicit Euler physics engine
 *  - 64 droplets (6 core, 22 satellite chunks, 36 mist droplets)
 *  - 19 electromagnets (center, inner 6, outer 12)
 *  - Underdamped spring ODEs for droplet radii & Rosensweig spikes
 *  - Kick, snare & stretch transient tear-offs and coalescence re-attachment ("دوباره بچسبه")
 *  - Pairwise surface tension cohesion, repulsion, swirling vortex & curl-noise drift
 *  - Full HDR GLSL fragment shader with Rosensweig hexagonal spikes & studio lighting
 *  - Real-time Audio DSP: 32 log bands, sub/bass/mid/air bands, spectral flux kick/snare detection
 *  - Direct audio file player with UI controls (working offline on file:// with zero permissions)
 *  - Synthetic demo beat synthesizer
 *  - Microphone input with permission error handling
 */

// ==========================================
// 1. WebGL 2.0 Initialization & Canvas Setup
// ==========================================
const canvas = document.getElementById('glcanvas');
const gl = canvas.getContext('webgl2', {
    alpha: true,
    premultipliedAlpha: true,
    antialias: true,
    powerPreference: 'high-performance'
});

if (!gl) {
    alert('دستگاه یا مرورگر شما از WebGL 2.0 پشتیبانی نمی‌کند.');
}

function resize() {
    const dpr = Math.min(window.devicePixelRatio || 1, 2.0);
    canvas.width = Math.round(window.innerWidth * dpr);
    canvas.height = Math.round(window.innerHeight * dpr);
    gl.viewport(0, 0, canvas.width, canvas.height);
}
window.addEventListener('resize', resize);
window.addEventListener('orientationchange', () => setTimeout(resize, 100));
resize();

// ==========================================
// 2. GLSL Shaders (Photorealistic Studio HDR)
// ==========================================
const vsSource = `#version 300 es
in vec2 inPosition;
out vec2 vPos;
void main() {
    vPos = inPosition;
    gl_Position = vec4(inPosition, 0.0, 1.0);
}`;

const fsSource = `#version 300 es
precision highp float;
in vec2 vPos;
out vec4 fragColor;

uniform vec2 uResolution;
uniform float uTime;
uniform int uBlobCount;
uniform vec4 uBlobs[64];      // x, y, r, weight
uniform vec4 uMagnets[19];    // x, y, strength, 0
uniform float uSpike;
uniform float uF0;
uniform vec3 uBodyColor;
uniform vec3 uRimColor;
uniform float uRimGain;
uniform float uGlintGain;
uniform float uShadowAlpha;
uniform float uIridescence;

#define ISO_T 0.35

// Helper for hex grid distance and cell center
vec2 getHexCenter(vec2 p, float s) {
    vec2 r = vec2(s, s * 1.7320508);
    vec2 h = r * 0.5;
    vec2 a = mod(p, r) - h;
    vec2 b = mod(p - h, r) - h;
    return dot(a, a) < dot(b, b) ? (p - a) : (p - b);
}

// Evaluate metaball potential field and analytic gradient
void evalMetaballs(vec2 p, out float f, out vec2 grad_f, out float r_local) {
    f = 0.0;
    grad_f = vec2(0.0);
    float sum_w = 0.0;
    float sum_wr = 0.0;
    const float support_scale = 1.840202;

    for (int i = 0; i < 64; ++i) {
        if (i >= uBlobCount) break;
        vec4 blob = uBlobs[i];
        vec2 c = blob.xy;
        float r_i = blob.z;
        float w_i = blob.w;

        float R_i = r_i * support_scale;
        vec2 d = p - c;
        float d2 = dot(d, d);
        float R2 = R_i * R_i;

        if (d2 >= R2) continue;

        float u = 1.0 - d2 / R2;
        float u2 = u * u;
        float u3 = u2 * u;

        f += w_i * u3;
        grad_f += w_i * (-6.0 * d * u2 / R2);
        sum_w += w_i * u;
        sum_wr += w_i * u * r_i;
    }
    r_local = sum_wr / max(sum_w, 1e-4);
}

// ACES Filmic Tonemapping
vec3 tonemapACES(vec3 x) {
    const float a = 2.51, b = 0.03, c = 2.43, d = 0.59, e = 0.14;
    return clamp((x * (a * x + b)) / (x * (c * x + d) + e), 0.0, 1.0);
}

// Linear to sRGB
vec3 linearToSRGB(vec3 color) {
    return pow(color, vec3(1.0 / 2.2));
}

// Procedural HDR Studio Lighting Environment
vec3 studioEnvironment(vec3 r, float edge_factor) {
    // Key Softbox: Upper-left overhead
    vec3 keyDir = normalize(vec3(-0.45, 0.65, 0.60));
    float keySoftbox = smoothstep(0.82, 0.98, dot(r, keyDir)) * 3.8;

    // Strip Rim-Box: Upper-right edge
    vec3 rimDir = normalize(vec3(0.68, 0.52, 0.51));
    float rimBox = smoothstep(0.89, 0.99, dot(r, rimDir)) * 2.6;

    // Pinpoint Spotlight: produces razor-sharp glossy glints
    vec3 spotDir = normalize(vec3(-0.15, 0.40, 0.90));
    float spotGlint = pow(max(dot(r, spotDir), 0.0), 256.0) * 12.0;

    // Studio Cyclorama Floor Bounce
    float floorBounce = (1.0 - smoothstep(-0.40, 0.15, r.z)) * edge_factor;
    vec3 floorColor = vec3(0.40, 0.43, 0.46) * 2.2;

    vec3 ambient = vec3(0.005, 0.006, 0.008);
    return ambient + vec3(1.0, 0.98, 0.95) * keySoftbox + vec3(0.92, 0.96, 1.0) * rimBox + vec3(1.0) * spotGlint + floorColor * floorBounce;
}

// Thin-film Iridescence
vec3 evalIridescence(float cosTheta, float thickness) {
    vec3 phase = vec3(0.0, 2.0, 4.0) + 7.0 * (1.0 - cosTheta) + 5.0 * thickness;
    return 0.5 + 0.5 * cos(phase);
}

void main() {
    // Map screen coordinates preserving aspect ratio
    float aspect = uResolution.x / uResolution.y;
    vec2 p = vPos;
    if (aspect > 1.0) p.x *= aspect; else p.y /= aspect;

    // 1. Evaluate Metaballs
    float f = 0.0;
    vec2 grad_f = vec2(0.0);
    float r_local = 0.1;
    evalMetaballs(p, f, grad_f, r_local);

    // 2. Rosensweig Hexagonal Spikes
    float B = 0.0;
    for (int k = 0; k < 19; ++k) {
        vec4 mag = uMagnets[k];
        if (mag.z <= 0.001) continue;
        vec2 m_pos = mag.xy;
        float d2 = dot(p - m_pos, p - m_pos);
        B += mag.z * exp(-d2 / 0.12);
    }

    float g = smoothstep(0.25, 0.80, B) * smoothstep(0.60 * ISO_T, 1.30 * ISO_T, f);
    float lambda = 0.085;
    vec2 warp = 0.012 * vec2(
        sin(35.0 * p.y + uTime * 0.5),
        cos(35.0 * p.x + uTime * 0.5)
    );
    vec2 p_hex = p + warp;
    vec2 hexCenter = getHexCenter(p_hex, lambda);
    vec2 d_vec = p_hex - hexCenter;
    float d_s = length(d_vec);

    float rho = 0.46 * lambda;
    float s = 0.0;
    vec2 grad_s = vec2(0.0);
    if (d_s < rho) {
        float q = clamp(1.0 - d_s / rho, 0.0, 1.0);
        s = q * q * (3.0 - 2.0 * q);
        grad_s = -6.0 * q * (1.0 - q) * (d_vec / max(d_s, 1e-5)) / rho;
    }

    float A_spike = 0.12;
    float spike_disp = A_spike * uSpike * g * s;
    float f_total = f + spike_disp;
    vec2 grad_total = grad_f + A_spike * uSpike * (grad_s * g);

    // 3. Signed Distance & Alpha
    float grad_len = max(length(grad_total), 1e-4);
    float sd = (f_total - ISO_T) / grad_len;
    float pixel_size = 2.0 / min(uResolution.x, uResolution.y);
    float alpha = clamp(0.5 + sd / pixel_size, 0.0, 1.0);

    // 4. 2.5D Meniscus Height-Field & Normal with capillary micro-ripples
    vec3 n = vec3(0.0, 0.0, 1.0);
    float h = 0.0;
    if (f_total > ISO_T) {
        float H_s = 0.45 * sqrt(clamp(r_local, 0.02, 0.35));
        float root_f = sqrt(max(f_total - ISO_T, 1e-5));
        h = H_s * root_f;
        vec2 grad_h = (H_s * grad_total) / (2.0 * max(root_f, 1e-3));

        float r_len = length(p);
        float ripple_k = 65.0;
        float ripple_grad = 0.0025 * ripple_k * cos(ripple_k * r_len - 8.0 * uTime);
        grad_h += ripple_grad * (p / max(r_len, 1e-4));

        n = normalize(vec3(-grad_h * 1.65, 1.0));
    }

    // 5. Studio Lighting & Shading
    vec3 v = vec3(0.0, 0.0, 1.0);
    vec3 r_vec = reflect(-v, n);
    float NdotV = max(dot(n, v), 0.0);
    float F = uF0 + (1.0 - uF0) * pow(1.0 - NdotV, 5.0);
    float edge_factor = 1.0 - smoothstep(1.0 * ISO_T, 1.75 * ISO_T, f_total);

    vec3 envRad = studioEnvironment(r_vec, edge_factor);
    vec3 body = uBodyColor * (1.0 - F);
    vec3 spec = envRad * F * uGlintGain;
    if (uIridescence > 0.0) {
        vec3 iriColor = evalIridescence(NdotV, h);
        spec += iriColor * uIridescence * F * 1.5;
    }
    float rimWeight = pow(1.0 - NdotV, 3.2) * edge_factor;
    vec3 rim = rimWeight * uRimColor * uRimGain;

    vec3 fluid_srgb = linearToSRGB(tonemapACES(body + spec + rim));

    // Triangular dither
    float dither = fract(sin(dot(gl_FragCoord.xy, vec2(12.9898, 78.233))) * 43758.5453);
    fluid_srgb += (dither - 0.5) / 255.0;
    fluid_srgb = clamp(fluid_srgb, 0.0, 1.0);

    // 6. Soft Drop Shadow
    vec2 shadowOffset = vec2(0.024, -0.032);
    float f_shadow = 0.0;
    vec2 dummy_grad = vec2(0.0);
    float dummy_r = 0.0;
    evalMetaballs(p - shadowOffset, f_shadow, dummy_grad, dummy_r);
    float shadow_alpha = uShadowAlpha * smoothstep(0.12, ISO_T, f_shadow) * (1.0 - alpha);

    // 7. Premultiplied Alpha Output
    float final_alpha = clamp(alpha + shadow_alpha, 0.0, 1.0);
    vec3 final_rgb = clamp(fluid_srgb * alpha, 0.0, final_alpha);

    // Circular containment falloff: eliminates rectangular clipping
    float r_screen = length(p);
    float edge_guard = 1.0 - smoothstep(0.82, 0.92, r_screen);
    final_alpha *= edge_guard;
    final_rgb *= edge_guard;

    fragColor = vec4(final_rgb, final_alpha);
}`;

function createShader(gl, type, source) {
    const s = gl.createShader(type);
    gl.shaderSource(s, source);
    gl.compileShader(s);
    if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) {
        console.error(gl.getShaderInfoLog(s));
        gl.deleteShader(s);
        return null;
    }
    return s;
}

const prog = gl.createProgram();
gl.attachShader(prog, createShader(gl, gl.VERTEX_SHADER, vsSource));
gl.attachShader(prog, createShader(gl, gl.FRAGMENT_SHADER, fsSource));
gl.linkProgram(prog);
if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) {
    console.error(gl.getProgramInfoLog(prog));
}
gl.useProgram(prog);

// Fullscreen Quad
const vao = gl.createVertexArray();
gl.bindVertexArray(vao);
const vbo = gl.createBuffer();
gl.bindBuffer(gl.ARRAY_BUFFER, vbo);
gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([
    -1, -1,  1, -1, -1,  1,
    -1,  1,  1, -1,  1,  1
]), gl.STATIC_DRAW);
const posLoc = gl.getAttribLocation(prog, 'inPosition');
gl.enableVertexAttribArray(posLoc);
gl.vertexAttribPointer(posLoc, 2, gl.FLOAT, false, 0, 0);

// Themes
const THEMES = {
    ink: { f0: 0.065, body: [0.01, 0.012, 0.016], rim: [0.75, 0.80, 0.85], rimGain: 0.65, glintGain: 1.0, shadow: 0.22, iri: 0.0 },
    mercury: { f0: 0.92, body: [0.80, 0.82, 0.85], rim: [0.95, 0.95, 1.0], rimGain: 0.85, glintGain: 1.2, shadow: 0.35, iri: 0.0 },
    oilslick: { f0: 0.065, body: [0.015, 0.015, 0.02], rim: [0.80, 0.70, 0.95], rimGain: 0.75, glintGain: 1.0, shadow: 0.22, iri: 0.75 },
    neon: { f0: 0.08, body: [0.008, 0.010, 0.016], rim: [0.0, 0.88, 1.0], rimGain: 1.65, glintGain: 1.25, shadow: 0.25, iri: 0.0 }
};
let currentTheme = 'ink';

// Uniform Locations
const uResLoc = gl.getUniformLocation(prog, 'uResolution');
const uTimeLoc = gl.getUniformLocation(prog, 'uTime');
const uBlobCountLoc = gl.getUniformLocation(prog, 'uBlobCount');
const uBlobsLoc = gl.getUniformLocation(prog, 'uBlobs');
const uMagnetsLoc = gl.getUniformLocation(prog, 'uMagnets');
const uSpikeLoc = gl.getUniformLocation(prog, 'uSpike');
const uF0Loc = gl.getUniformLocation(prog, 'uF0');
const uBodyColorLoc = gl.getUniformLocation(prog, 'uBodyColor');
const uRimColorLoc = gl.getUniformLocation(prog, 'uRimColor');
const uRimGainLoc = gl.getUniformLocation(prog, 'uRimGain');
const uGlintGainLoc = gl.getUniformLocation(prog, 'uGlintGain');
const uShadowAlphaLoc = gl.getUniformLocation(prog, 'uShadowAlpha');
const uIridescenceLoc = gl.getUniformLocation(prog, 'uIridescence');


// ==========================================
// 3. Fluid Physics Engine (Matches Linux Python)
// ==========================================
const N_BLOBS = 64;
const N_CORE = 6;
const N_SAT = 22;
const N_MIST = 36;
const N_MAGNETS = 19;

// Preallocated physics arrays
const pos = new Float32Array(N_BLOBS * 2);
const vel = new Float32Array(N_BLOBS * 2);
const forces = new Float32Array(N_BLOBS * 2);
const weights = new Float32Array(N_BLOBS);
const r0 = new Float32Array(N_BLOBS);
const r = new Float32Array(N_BLOBS);
const r_vel = new Float32Array(N_BLOBS);
const r_target = new Float32Array(N_BLOBS);

const detached = new Uint8Array(N_BLOBS);
const detach_timer = new Float32Array(N_BLOBS);
const target_flight_time = new Float32Array(N_BLOBS);
const cooldown = new Float32Array(N_BLOBS);
let pinch_accumulator = 0.0;

// Underdamped Spring constants
const r_zeta = 0.55;
const r_omega = 18.0;

let spike = 0.0;
let spike_vel = 0.0;
let spike_target = 0.0;
const spike_zeta = 0.45;
const spike_omega = 24.0;

// Preset parameters
const viscosity = 1.0;
const magnet_gain = 0.70;
const kick_impulse = 0.95;
const spike_amount = 0.35;
const max_flying = 20;

// 19 Electromagnets
const magnet_pos = new Float32Array(N_MAGNETS * 2);
const magnet_str = new Float32Array(N_MAGNETS);
const magnets_uniform = new Float32Array(N_MAGNETS * 4);
const blobs_uniform = new Float32Array(N_BLOBS * 4);

// Initialize Magnet Positions
magnet_pos[0] = 0.0;
magnet_pos[1] = 0.0;
// Inner ring (6 magnets at r = 0.30)
for (let i = 0; i < 6; i++) {
    const angle = (2.0 * Math.PI * i) / 6.0;
    magnet_pos[(1 + i) * 2] = 0.30 * Math.cos(angle);
    magnet_pos[(1 + i) * 2 + 1] = 0.30 * Math.sin(angle);
}
// Outer ring (12 magnets at r = 0.62)
for (let i = 0; i < 12; i++) {
    const angle = (2.0 * Math.PI * i) / 12.0;
    magnet_pos[(7 + i) * 2] = 0.62 * Math.cos(angle);
    magnet_pos[(7 + i) * 2 + 1] = 0.62 * Math.sin(angle);
}
for (let i = 0; i < N_MAGNETS; i++) {
    magnets_uniform[i * 4] = magnet_pos[i * 2];
    magnets_uniform[i * 4 + 1] = magnet_pos[i * 2 + 1];
}

// Initialize Droplets Hierarchy
function initDroplets() {
    detached.fill(0);
    detach_timer.fill(0);
    target_flight_time.fill(0);
    cooldown.fill(0);
    pinch_accumulator = 0.0;

    // 6 core blobs (mother mass)
    for (let i = 0; i < N_CORE; i++) {
        const r_val = 0.10 + Math.random() * 0.055;
        r0[i] = r_val;
        r[i] = r_val;
        r_target[i] = r_val;
        weights[i] = 1.0;
        const angle = Math.random() * Math.PI * 2;
        const dist = 0.02 + Math.random() * 0.04;
        pos[i * 2] = dist * Math.cos(angle);
        pos[i * 2 + 1] = dist * Math.sin(angle);
    }

    // 22 satellite chunks (tear off and reattach)
    for (let i = N_CORE; i < N_CORE + N_SAT; i++) {
        const r_val = 0.055 + Math.random() * 0.040;
        r0[i] = r_val;
        r[i] = r_val;
        r_target[i] = r_val;
        weights[i] = 0.90;
        const angle = Math.random() * Math.PI * 2;
        const dist = 0.16 + Math.random() * 0.09;
        pos[i * 2] = dist * Math.cos(angle);
        pos[i * 2 + 1] = dist * Math.sin(angle);
    }

    // 36 mist droplets / micro-chunks
    for (let i = N_CORE + N_SAT; i < N_BLOBS; i++) {
        const r_val = 0.025 + Math.random() * 0.023;
        r0[i] = r_val;
        r[i] = r_val;
        r_target[i] = r_val;
        weights[i] = 0.78;
        const angle = Math.random() * Math.PI * 2;
        const dist = 0.14 + Math.random() * 0.09;
        pos[i * 2] = dist * Math.cos(angle);
        pos[i * 2 + 1] = dist * Math.sin(angle);
    }

    // Pre-detach a set of droplets for immediate organic life on startup
    const initDetachedIdx = [7, 10, 14, 18, 22, 26, 32, 38, 44, 50, 56, 62];
    for (const idx of initDetachedIdx) {
        detached[idx] = 1;
        target_flight_time[idx] = 1.8 + Math.random() * 1.4;
        detach_timer[idx] = 0.2 + Math.random() * 1.0;
        const angle = Math.random() * Math.PI * 2;
        const dist = 0.30 + Math.random() * 0.20;
        pos[idx * 2] = dist * Math.cos(angle);
        pos[idx * 2 + 1] = dist * Math.sin(angle);
    }
}
initDroplets();

// Physics state tracking
let prev_kick = 0.0;
let prev_snare = 0.0;
let simTime = 0.0;
let accumulated_dt = 0.0;
const DT_SIM = 1.0 / 120.0;
const SUPPORT_SCALE = 1.840202;

// Vectorized choreography step matching fluid.py
function updateChoreography(feat, deltaSeconds) {
    const clamped_dt = Math.min(deltaSeconds, 0.10);
    accumulated_dt += clamped_dt;

    // Transient impulse triggers
    const kick_jump = Math.max(0.0, feat.kick - prev_kick);
    const snare_jump = Math.max(0.0, feat.snare - prev_snare);
    prev_kick = feat.kick;
    prev_snare = feat.snare;

    // Magnet 0: center magnet
    magnet_str[0] = (0.65 + 0.35 * feat.sub + 0.25 * feat.kick) * magnet_gain;

    // Outer ring rotation (2*pi / 90.0 rad/s)
    const rot_angle = (2.0 * Math.PI / 90.0) * simTime;

    // Inner ring (lowmid & mid)
    for (let i = 0; i < 6; i++) {
        const val = (0.35 * feat.lowmid + 0.25 * feat.mid) * (1.0 + 0.25 * Math.sin(rot_angle + i));
        magnet_str[1 + i] = val * magnet_gain;
    }

    // Outer ring (32 bands folded into 12 sectors)
    for (let i = 0; i < 12; i++) {
        const band_idx = Math.floor((i / 12.0) * 32) % 32;
        const val = feat.bands[band_idx] * 0.40 + 0.20 * feat.highmid + 0.15 * feat.air + 0.25 * feat.hat;
        const x_m = magnet_pos[(7 + i) * 2];
        const bias = 1.0 + 0.35 * feat.balance * (x_m >= 0 ? 1.0 : -1.0);
        magnet_str[7 + i] = val * bias * magnet_gain;
    }

    // Radii underdamped targets with organic idle breathing
    const idle_breath = 0.04 * Math.sin(2.5 * simTime);
    for (let i = 0; i < N_BLOBS; i++) {
        const band_val = feat.bands[i % 32];
        r_target[i] = r0[i] * (1.0 + 0.08 * band_val + 0.10 * feat.bass + idle_breath);
    }

    // Rosensweig spike target
    spike_target = Math.min(1.0, 0.45 * feat.bass + 0.55 * feat.sub + 0.45 * feat.kick) * spike_amount;

    // Count currently flying droplets
    let n_flying = 0;
    for (let i = N_CORE; i < N_BLOBS; i++) {
        if (detached[i]) n_flying++;
    }

    // Core mass center
    let p_core_x = 0.0, p_core_y = 0.0;
    for (let i = 0; i < N_CORE; i++) {
        p_core_x += pos[i * 2];
        p_core_y += pos[i * 2 + 1];
    }
    p_core_x /= N_CORE;
    p_core_y /= N_CORE;

    // A. Kick Transient Tear-Off Trigger
    if ((kick_jump > 0.08 || (feat.kick > 0.55 && kick_jump > 0.03)) && n_flying < max_flying) {
        const candidates = [];
        for (let i = N_CORE; i < N_BLOBS; i++) {
            if (!detached[i] && cooldown[i] <= 0.0) {
                const dx = pos[i * 2] - p_core_x;
                const dy = pos[i * 2 + 1] - p_core_y;
                candidates.push({ idx: i, dist: Math.sqrt(dx * dx + dy * dy) });
            }
        }
        candidates.sort((a, b) => b.dist - a.dist);

        const kj = Math.max(kick_jump, feat.kick * 0.40);
        const allowed = max_flying - n_flying;
        let n_eject = 1;
        if (kj > 0.30) n_eject = Math.min(candidates.length, Math.min(allowed, 4));
        else if (kj > 0.18) n_eject = Math.min(candidates.length, Math.min(allowed, 2));
        else n_eject = Math.min(candidates.length, Math.min(allowed, 1));

        for (let k = 0; k < n_eject; k++) {
            const c = candidates[k].idx;
            detached[c] = 1;
            detach_timer[c] = 0.0;
            target_flight_time[c] = (1.4 + Math.random() * 1.4) * (1.0 + 0.25 * feat.kick);

            const rx = pos[c * 2] - p_core_x;
            const ry = pos[c * 2 + 1] - p_core_y;
            const d_rel = Math.sqrt(rx * rx + ry * ry) + 1e-4;
            const rad_x = rx / d_rel;
            const rad_y = ry / d_rel;
            const tang_x = -rad_y;
            const tang_y = rad_x;
            const scatter = -0.50 + Math.random();

            let dir_x = rad_x + scatter * tang_x;
            let dir_y = rad_y + scatter * tang_y;
            const d_len = Math.sqrt(dir_x * dir_x + dir_y * dir_y) + 1e-4;
            dir_x /= d_len;
            dir_y /= d_len;

            const speed = (2.8 + 3.2 * kj) * kick_impulse;
            vel[c * 2] = dir_x * speed;
            vel[c * 2 + 1] = dir_y * speed;
        }
        n_flying += n_eject;
    }

    // B. Snare Transient Tear-Off Trigger
    if (snare_jump > 0.14 && n_flying < max_flying) {
        const candidates = [];
        for (let i = N_CORE; i < N_BLOBS; i++) {
            if (!detached[i] && cooldown[i] <= 0.0) candidates.push(i);
        }
        if (candidates.length > 0) {
            const c = candidates[Math.floor(Math.random() * candidates.length)];
            detached[c] = 1;
            detach_timer[c] = 0.0;
            target_flight_time[c] = 1.2 + Math.random() * 1.2;

            const rx = pos[c * 2] - p_core_x;
            const ry = pos[c * 2 + 1] - p_core_y;
            const d_rel = Math.sqrt(rx * rx + ry * ry) + 1e-4;
            const rad_x = rx / d_rel;
            const rad_y = ry / d_rel;
            const tang_x = -rad_y;
            const tang_y = rad_x;

            let dir_x = 0.35 * rad_x + 0.90 * tang_x;
            let dir_y = 0.35 * rad_y + 0.90 * tang_y;
            const d_len = Math.sqrt(dir_x * dir_x + dir_y * dir_y) + 1e-4;
            dir_x /= d_len;
            dir_y /= d_len;

            const speed = 2.6 + 2.2 * snare_jump;
            vel[c * 2] = dir_x * speed;
            vel[c * 2 + 1] = dir_y * speed;
            n_flying++;
        }
    }

    // C. Ambient / Periodic Pinch-Off
    pinch_accumulator += clamped_dt;
    const interval = 0.45 / (1.0 + 1.2 * feat.loudness + 0.5 * feat.bass);
    if (pinch_accumulator >= interval) {
        pinch_accumulator = 0.0;
        if (n_flying < max_flying) {
            let max_d = -1;
            let pick = -1;
            for (let i = N_CORE; i < N_BLOBS; i++) {
                if (!detached[i] && cooldown[i] <= 0.0) {
                    const dx = pos[i * 2] - p_core_x;
                    const dy = pos[i * 2 + 1] - p_core_y;
                    const d = dx * dx + dy * dy;
                    if (d > max_d) { max_d = d; pick = i; }
                }
            }
            if (pick >= 0) {
                detached[pick] = 1;
                detach_timer[pick] = 0.0;
                target_flight_time[pick] = 1.5 + Math.random() * 1.5;

                const rx = pos[pick * 2] - p_core_x;
                const ry = pos[pick * 2 + 1] - p_core_y;
                const d_rel = Math.sqrt(rx * rx + ry * ry) + 1e-4;
                const rad_x = rx / d_rel;
                const rad_y = ry / d_rel;
                const tang_x = -rad_y;
                const tang_y = rad_x;
                const scatter = -0.40 + Math.random() * 0.80;

                let dir_x = rad_x + scatter * tang_x;
                let dir_y = rad_y + scatter * tang_y;
                const d_len = Math.sqrt(dir_x * dir_x + dir_y * dir_y) + 1e-4;
                dir_x /= d_len;
                dir_y /= d_len;

                const speed = 2.2 + Math.random() * 1.2;
                vel[pick * 2] = dir_x * speed;
                vel[pick * 2 + 1] = dir_y * speed;
            }
        }
    }

    // Run fixed substeps
    while (accumulated_dt >= DT_SIM) {
        substep(DT_SIM, feat);
        accumulated_dt -= DT_SIM;
        simTime += DT_SIM;
    }
}

// Single 120/240 Hz semi-implicit Euler integration step
function substep(dt, feat) {
    forces.fill(0.0);

    // 1. Underdamped Spring ODEs for Radii
    for (let i = 0; i < N_BLOBS; i++) {
        const r_acc = -2.0 * r_zeta * r_omega * r_vel[i] - (r_omega * r_omega) * (r[i] - r_target[i]);
        r_vel[i] += r_acc * dt;
        r[i] += r_vel[i] * dt;
        if (r[i] < 0.015) r[i] = 0.015;
        else if (r[i] > 0.35) r[i] = 0.35;
    }

    // Rosensweig Spike Amount Spring
    const spike_acc = -2.0 * spike_zeta * spike_omega * spike_vel - (spike_omega * spike_omega) * (spike - spike_target);
    spike_vel += spike_acc * dt;
    spike += spike_vel * dt;
    spike = Math.max(0.0, Math.min(2.0, spike));

    // 2. Cooldowns and Center of Core Mass
    let p_core_x = 0.0, p_core_y = 0.0;
    for (let i = 0; i < N_BLOBS; i++) {
        if (cooldown[i] > 0.0) cooldown[i] = Math.max(0.0, cooldown[i] - dt);
        if (detached[i]) detach_timer[i] += dt;
        if (i < N_CORE) {
            p_core_x += pos[i * 2];
            p_core_y += pos[i * 2 + 1];
        }
    }
    p_core_x /= N_CORE;
    p_core_y /= N_CORE;

    // Pull core towards touch target or origin
    const targetX = touchActive ? touchPos[0] * 0.65 : 0.0;
    const targetY = touchActive ? touchPos[1] * 0.65 : 0.0;
    const off_x = p_core_x - targetX;
    const off_y = p_core_y - targetY;
    const d_core = Math.sqrt(off_x * off_x + off_y * off_y);
    if (d_core > 0.01) {
        for (let i = 0; i < N_CORE; i++) {
            forces[i * 2] -= 4.5 * off_x;
            forces[i * 2 + 1] -= 4.5 * off_y;
        }
    }

    // 3. Droplet Flight, Restoring Spring, Coalescence ("دوباره بچسبه") & Perimeter Tether
    let n_flying = 0;
    for (let i = N_CORE; i < N_BLOBS; i++) {
        if (detached[i]) n_flying++;
    }

    for (let i = N_CORE; i < N_BLOBS; i++) {
        const dx = pos[i * 2] - p_core_x;
        const dy = pos[i * 2 + 1] - p_core_y;
        const dist_c = Math.sqrt(dx * dx + dy * dy) + 1e-5;
        const inv_ux = -dx / dist_c;
        const inv_uy = -dy / dist_c;

        if (detached[i]) {
            // A. Detached Droplet Flight: Ramping inward restoring pull
            const flight_target = Math.max(target_flight_time[i], 0.1);
            const tau = detach_timer[i] / flight_target;
            const ramp = Math.max(0.0, Math.min(1.0, (tau - 0.60) / 0.35));
            const k_return = 0.15 + 1.8 * ramp;
            forces[i * 2] += inv_ux * (k_return * dist_c);
            forces[i * 2 + 1] += inv_uy * (k_return * dist_c);

            // B. Coalescence / Re-attachment check ("دوباره بچسبه")
            const v_inward = vel[i * 2] * inv_ux + vel[i * 2 + 1] * inv_uy;
            if (detach_timer[i] > 0.45 && dist_c < (0.15 + r[i]) && v_inward > 0.0) {
                detached[i] = 0;
                detach_timer[i] = 0.0;
                cooldown[i] = 0.25 + Math.random() * 0.40;

                // Momentum absorption & recoil to core
                const recoil_x = weights[i] * vel[i * 2] * 0.70;
                const recoil_y = weights[i] * vel[i * 2 + 1] * 0.70;
                vel[i * 2] *= 0.25;
                vel[i * 2 + 1] *= 0.25;

                const core_push_x = (recoil_x / (N_CORE * weights[0])) * 0.15;
                const core_push_y = (recoil_y / (N_CORE * weights[0])) * 0.15;
                for (let k = 0; k < N_CORE; k++) {
                    vel[k * 2] += core_push_x;
                    vel[k * 2 + 1] += core_push_y;
                }
            }
        } else {
            // C. Attached Droplets: Perimeter tether
            const target_d = 0.17 + 0.05 * Math.sin(i * 1.3);
            const excess_d = Math.max(0.0, dist_c - target_d);
            forces[i * 2] += inv_ux * (3.8 * excess_d);
            forces[i * 2 + 1] += inv_uy * (3.8 * excess_d);

            // Stretch pinch-off
            const v_inward = vel[i * 2] * inv_ux + vel[i * 2 + 1] * inv_uy;
            if (n_flying < max_flying && dist_c > (0.35 + r[i]) && v_inward < -0.2 && cooldown[i] <= 0.0) {
                detached[i] = 1;
                detach_timer[i] = 0.0;
                target_flight_time[i] = 1.6 + Math.random() * 1.4;
                n_flying++;
            }
        }
    }

    // 4. Magnetic Attraction across all 19 magnets
    const eps2 = 0.08 * 0.08;
    const G = 4.2;
    for (let i = 0; i < N_BLOBS; i++) {
        let px = pos[i * 2];
        let py = pos[i * 2 + 1];
        let total_fm_x = 0.0;
        let total_fm_y = 0.0;

        for (let m = 0; m < N_MAGNETS; m++) {
            const dx_m = magnet_pos[m * 2] - px;
            const dy_m = magnet_pos[m * 2 + 1] - py;
            const dist2_m = dx_m * dx_m + dy_m * dy_m;
            const denom = Math.pow(dist2_m + eps2, 1.25);

            let fm_x = G * (magnet_str[m] * dx_m) / denom;
            let fm_y = G * (magnet_str[m] * dy_m) / denom;

            // Attenuate center magnet during early outward flight
            if (m === 0 && detached[i] && detach_timer[i] < 0.50 * Math.max(target_flight_time[i], 0.1)) {
                fm_x *= 0.10;
                fm_y *= 0.10;
            }

            const flen = Math.sqrt(fm_x * fm_x + fm_y * fm_y) + 1e-5;
            const scale = Math.min(1.0, 15.0 / flen);
            total_fm_x += fm_x * scale;
            total_fm_y += fm_y * scale;
        }
        forces[i * 2] += total_fm_x;
        forces[i * 2 + 1] += total_fm_y;
    }

    // 5. Pairwise Droplet Interactions (Surface Tension Cohesion + Repulsion)
    for (let i = 0; i < N_BLOBS; i++) {
        const px_i = pos[i * 2];
        const py_i = pos[i * 2 + 1];
        const r_i = r[i];
        const det_i = detached[i];
        const isCore_i = i < N_CORE;

        for (let j = i + 1; j < N_BLOBS; j++) {
            const dx = pos[j * 2] - px_i;
            const dy = pos[j * 2 + 1] - py_i;
            const dist = Math.sqrt(dx * dx + dy * dy) + 1e-5;
            const dir_x = dx / dist;
            const dir_y = dy / dist;
            const sum_r = r_i + r[j];

            let f_net = 0.0;
            const isCore_j = j < N_CORE;
            const det_j = detached[j];

            if (isCore_i && isCore_j) {
                // Core-to-core cohesion
                if (dist > 1.05 * sum_r && dist < 2.2 * sum_r) {
                    f_net += 2.5 * ((dist - 1.05 * sum_r) / sum_r);
                }
            } else if (!det_i && !det_j) {
                // Attached-to-attached cohesion
                if (dist > 1.05 * sum_r && dist < 2.0 * sum_r) {
                    f_net += 1.8 * ((dist - 1.05 * sum_r) / sum_r);
                }
            }

            // Repulsion
            const rep_thresh = (det_i && det_j) ? (1.35 * sum_r) : (0.80 * sum_r);
            if (dist < rep_thresh) {
                f_net -= 4.5 * ((rep_thresh - dist) / sum_r);
            }

            forces[i * 2] += f_net * dir_x;
            forces[i * 2 + 1] += f_net * dir_y;
            forces[j * 2] -= f_net * dir_x;
            forces[j * 2 + 1] -= f_net * dir_y;
        }
    }

    // 6. Continuous Swirling Vortex + Curl-Noise Drift
    const swirl_torque = 0.50 + 0.90 * feat.loudness + 1.20 * feat.snare;
    const curl_scale = 0.35 * (1.0 + 0.60 * feat.loudness + 0.40 * feat.excitement);

    for (let i = 0; i < N_BLOBS; i++) {
        const px = pos[i * 2];
        const py = pos[i * 2 + 1];
        const d_origin = Math.sqrt(px * px + py * py) + 1e-4;

        // Tangent swirl
        const tangent_x = -py / d_origin;
        const tangent_y = px / d_origin;
        forces[i * 2] += tangent_x * swirl_torque;
        forces[i * 2 + 1] += tangent_y * swirl_torque;

        // Curl noise
        const curl_x = -2.0 * Math.PI * Math.sin(2.0 * Math.PI * px) * Math.sin(2.0 * Math.PI * py) + Math.PI * Math.cos(4.0 * Math.PI * py);
        const curl_y = -2.0 * Math.PI * Math.cos(2.0 * Math.PI * px) * Math.cos(2.0 * Math.PI * py);
        forces[i * 2] += curl_x * curl_scale;
        forces[i * 2 + 1] += curl_y * curl_scale;

        // Progressive inward boundary cushion
        const safe_chamber_r = 0.80;
        const max_r_center = Math.max(0.35, safe_chamber_r - r[i] * SUPPORT_SCALE);
        const cushion_zone = 0.12;
        const soft_r = Math.max(0.20, max_r_center - cushion_zone);
        if (d_origin > soft_r) {
            const inv_p = 1.0 / d_origin;
            const nx = px * inv_p;
            const ny = py * inv_p;
            const cush_ratio = Math.max(0.0, Math.min(1.0, (d_origin - soft_r) / cushion_zone));
            const f_cush = -5.5 * Math.pow(cush_ratio, 1.5);
            forces[i * 2] += f_cush * nx;
            forces[i * 2 + 1] += f_cush * ny;
        }

        // Viscous drag
        const c_drag = 2.4 * viscosity;
        forces[i * 2] -= c_drag * vel[i * 2];
        forces[i * 2 + 1] -= c_drag * vel[i * 2 + 1];

        // Semi-implicit Euler integration
        const inv_w = 1.0 / weights[i];
        vel[i * 2] += forces[i * 2] * inv_w * dt;
        vel[i * 2 + 1] += forces[i * 2 + 1] * inv_w * dt;

        // Speed clamp
        const v_sq = vel[i * 2] * vel[i * 2] + vel[i * 2 + 1] * vel[i * 2 + 1];
        const v_norm = Math.sqrt(v_sq) + 1e-5;
        if (v_norm > 6.0) {
            const v_scale = 6.0 / v_norm;
            vel[i * 2] *= v_scale;
            vel[i * 2 + 1] *= v_scale;
        }

        pos[i * 2] += vel[i * 2] * dt;
        pos[i * 2 + 1] += vel[i * 2 + 1] * dt;

        // Chamber wall containment & bounce
        const cur_d = Math.sqrt(pos[i * 2] * pos[i * 2] + pos[i * 2 + 1] * pos[i * 2 + 1]);
        if (cur_d > max_r_center) {
            const inv_p = 1.0 / Math.max(cur_d, 1e-5);
            const nx = pos[i * 2] * inv_p;
            const ny = pos[i * 2 + 1] * inv_p;
            const penetration = cur_d - max_r_center;

            pos[i * 2] -= nx * penetration;
            pos[i * 2 + 1] -= ny * penetration;

            const v_dot_n = vel[i * 2] * nx + vel[i * 2 + 1] * ny;
            if (v_dot_n > 0.0) {
                vel[i * 2] -= 1.25 * v_dot_n * nx;
                vel[i * 2 + 1] -= 1.25 * v_dot_n * ny;
            }
        }
    }
}

// Pack uniforms for GLSL
function packUniforms() {
    for (let i = 0; i < N_BLOBS; i++) {
        blobs_uniform[i * 4] = pos[i * 2];
        blobs_uniform[i * 4 + 1] = pos[i * 2 + 1];
        blobs_uniform[i * 4 + 2] = r[i];
        blobs_uniform[i * 4 + 3] = weights[i];
    }
    for (let i = 0; i < N_MAGNETS; i++) {
        magnets_uniform[i * 4 + 2] = magnet_str[i];
    }
}


// ==========================================
// 4. Audio DSP & Analysis Pipeline
// ==========================================
let audioCtx = null;
let analyserNode = null;
let audioByteFreq = null;
let micStream = null;
let micSourceNode = null;
let fileSourceNode = null;

// Track transient history
let prevBassEnergy = 0.0;
let prevSnareEnergy = 0.0;
let prevHatEnergy = 0.0;
let excitementEMA = 0.0;

const featState = {
    bands: new Float32Array(32),
    sub: 0.0,
    bass: 0.0,
    lowmid: 0.0,
    mid: 0.0,
    highmid: 0.0,
    air: 0.0,
    loudness: 0.0,
    excitement: 0.0,
    kick: 0.0,
    snare: 0.0,
    hat: 0.0,
    balance: 0.0,
    is_silent: true
};

function initAudioContext() {
    if (!audioCtx) {
        const AudioContextClass = window.AudioContext || window.webkitAudioContext;
        audioCtx = new AudioContextClass();
    }
    if (audioCtx.state === 'suspended') {
        audioCtx.resume();
    }
    if (!analyserNode) {
        analyserNode = audioCtx.createAnalyser();
        analyserNode.fftSize = 1024;
        analyserNode.smoothingTimeConstant = 0.25;
        analyserNode.minDecibels = -90;
        analyserNode.maxDecibels = -10;
        audioByteFreq = new Uint8Array(analyserNode.frequencyBinCount);
    }
    return audioCtx;
}

// Calculate average energy in Hz range
function getFrequencyRangeEnergy(fStart, fEnd, sampleRate, numBins) {
    const binWidth = (sampleRate / 2.0) / numBins;
    const startBin = Math.max(0, Math.floor(fStart / binWidth));
    const endBin = Math.min(numBins - 1, Math.ceil(fEnd / binWidth));
    if (endBin <= startBin) return (audioByteFreq[startBin] || 0) / 255.0;

    let sum = 0;
    for (let b = startBin; b <= endBin; b++) {
        sum += audioByteFreq[b];
    }
    return (sum / (endBin - startBin + 1)) / 255.0;
}

// Extract full feature set matching Python AudioAnalyzer
function extractAudioFeatures(deltaSec) {
    if (!analyserNode || !audioByteFreq) {
        // Fallback organic breathing motion
        featState.is_silent = true;
        featState.sub = 0.15;
        featState.bass = 0.20 + 0.15 * Math.sin(simTime * 2.8) * Math.cos(simTime * 1.4);
        featState.lowmid = 0.1;
        featState.mid = 0.1;
        featState.highmid = 0.05;
        featState.air = 0.02;
        featState.loudness = 0.15;
        featState.kick = Math.max(0.0, featState.kick * Math.exp(-deltaSec / 0.120));
        featState.snare = Math.max(0.0, featState.snare * Math.exp(-deltaSec / 0.160));
        featState.hat = Math.max(0.0, featState.hat * Math.exp(-deltaSec / 0.060));
        for (let i = 0; i < 32; i++) {
            featState.bands[i] = 0.15 + 0.10 * Math.sin(simTime * 1.5 + i * 0.4);
        }
        return featState;
    }

    analyserNode.getByteFrequencyData(audioByteFreq);
    const sampleRate = audioCtx.sampleRate || 48000;
    const numBins = analyserNode.frequencyBinCount;

    // 1. Grouped bands
    const sub = getFrequencyRangeEnergy(30, 60, sampleRate, numBins);
    const bass = getFrequencyRangeEnergy(60, 250, sampleRate, numBins);
    const lowmid = getFrequencyRangeEnergy(250, 500, sampleRate, numBins);
    const mid = getFrequencyRangeEnergy(500, 2000, sampleRate, numBins);
    const highmid = getFrequencyRangeEnergy(2000, 6000, sampleRate, numBins);
    const air = getFrequencyRangeEnergy(6000, 16000, sampleRate, numBins);

    // 2. 32 Logarithmic Bands from 30 Hz to 16 kHz
    for (let i = 0; i < 32; i++) {
        const fCenter = 30.0 * Math.pow(16000.0 / 30.0, i / 31.0);
        const fLow = fCenter * 0.85;
        const fHigh = fCenter * 1.15;
        featState.bands[i] = getFrequencyRangeEnergy(fLow, fHigh, sampleRate, numBins);
    }

    featState.sub = sub;
    featState.bass = bass;
    featState.lowmid = lowmid;
    featState.mid = mid;
    featState.highmid = highmid;
    featState.air = air;

    // Overall RMS Loudness
    const loudness = (sub * 0.25 + bass * 0.35 + mid * 0.25 + highmid * 0.15);
    featState.loudness = loudness;
    featState.is_silent = loudness < 0.015;

    // Excitement EMA (~6s)
    excitementEMA += (loudness - excitementEMA) * (1.0 - Math.exp(-deltaSec / 6.0));
    featState.excitement = excitementEMA;

    // 3. Transient Onset Detection (Kick, Snare, Hat) with exponential decay
    const bassEnergy = sub * 0.65 + bass * 0.35;
    const kickFlux = Math.max(0.0, bassEnergy - prevBassEnergy);
    prevBassEnergy = bassEnergy;

    if (kickFlux > 0.06) {
        featState.kick = Math.min(1.0, featState.kick + kickFlux * 2.8);
    } else {
        featState.kick *= Math.exp(-deltaSec / 0.120);
    }

    const snareEnergy = lowmid * 0.50 + highmid * 0.50;
    const snareFlux = Math.max(0.0, snareEnergy - prevSnareEnergy);
    prevSnareEnergy = snareEnergy;

    if (snareFlux > 0.08) {
        featState.snare = Math.min(1.0, featState.snare + snareFlux * 2.5);
    } else {
        featState.snare *= Math.exp(-deltaSec / 0.160);
    }

    const hatFlux = Math.max(0.0, air - prevHatEnergy);
    prevHatEnergy = air;

    if (hatFlux > 0.07) {
        featState.hat = Math.min(1.0, featState.hat + hatFlux * 2.5);
    } else {
        featState.hat *= Math.exp(-deltaSec / 0.060);
    }

    return featState;
}


// ==========================================
// 5. Song Player & Audio File Handling
// ==========================================
const audioEl = document.getElementById('audio-element');
const fileInput = document.getElementById('audio-file-input');
const audioFileBtn = document.getElementById('audio-file-btn');
const playerCard = document.getElementById('player-card');
const trackNameEl = document.getElementById('track-name');
const trackTimeEl = document.getElementById('track-time');
const trackProgress = document.getElementById('track-progress');
const playPauseBtn = document.getElementById('play-pause-btn');
const closePlayerBtn = document.getElementById('close-player-btn');
const micBtn = document.getElementById('mic-btn');
const demoBtn = document.getElementById('demo-btn');
const toastEl = document.getElementById('toast');

let toastTimeout = null;
function showToast(message, type = 'info', duration = 4000) {
    if (toastTimeout) clearTimeout(toastTimeout);
    toastEl.textContent = message;
    toastEl.className = 'show ' + type;
    toastTimeout = setTimeout(() => {
        toastEl.className = '';
    }, duration);
}

let prevFileUrl = null;

// Connect Audio Element to Web Audio API
function connectAudioElement() {
    initAudioContext();
    if (!fileSourceNode) {
        fileSourceNode = audioCtx.createMediaElementSource(audioEl);
        fileSourceNode.connect(analyserNode);
        fileSourceNode.connect(audioCtx.destination); // Direct audio out (analyserNode remains isolated)
    }
}

// Trigger file selection
audioFileBtn.addEventListener('click', () => {
    initAudioContext();
    fileInput.value = '';
    fileInput.click();
});

fileInput.addEventListener('change', (e) => {
    const file = e.target.files[0];
    if (!file) return;

    // Disconnect demo or mic
    stopDemoSynth();
    stopMic();

    connectAudioElement();

    if (prevFileUrl) {
        URL.revokeObjectURL(prevFileUrl);
    }
    const fileUrl = URL.createObjectURL(file);
    prevFileUrl = fileUrl;
    audioEl.src = fileUrl;
    audioEl.play().then(() => {
        trackNameEl.textContent = '🎵 ' + file.name;
        playerCard.classList.add('active');
        playPauseBtn.textContent = '⏸️';
        audioFileBtn.classList.add('active');
        showToast('آهنگ در حال پخش است - فروسیال با موزیک می‌رقصد', 'success');
    }).catch(err => {
        console.error('Audio play error:', err);
        showToast('خطا در پخش آهنگ: ' + err.message, 'error');
    });
});

// Play / Pause Toggle
playPauseBtn.addEventListener('click', () => {
    if (audioEl.paused) {
        initAudioContext();
        audioEl.play();
        playPauseBtn.textContent = '⏸️';
    } else {
        audioEl.pause();
        playPauseBtn.textContent = '▶️';
    }
});

// Close player
closePlayerBtn.addEventListener('click', () => {
    audioEl.pause();
    audioEl.currentTime = 0;
    if (prevFileUrl) {
        URL.revokeObjectURL(prevFileUrl);
        prevFileUrl = null;
    }
    trackProgress.value = 0;
    trackTimeEl.textContent = '0:00 / 0:00';
    playerCard.classList.remove('active');
    audioFileBtn.classList.remove('active');
    stopDemoSynth();
    showToast('پخش متوقف شد');
});

// Update audio progress bar & timer
function formatTime(sec) {
    if (isNaN(sec)) return '0:00';
    const m = Math.floor(sec / 60);
    const s = Math.floor(sec % 60);
    return m + ':' + (s < 10 ? '0' : '') + s;
}

audioEl.addEventListener('timeupdate', () => {
    if (!audioEl.duration) return;
    const progress = (audioEl.currentTime / audioEl.duration) * 100;
    trackProgress.value = progress;
    trackTimeEl.textContent = formatTime(audioEl.currentTime) + ' / ' + formatTime(audioEl.duration);
});

trackProgress.addEventListener('input', () => {
    if (audioEl.duration) {
        audioEl.currentTime = (trackProgress.value / 100) * audioEl.duration;
    }
});

audioEl.addEventListener('ended', () => {
    playPauseBtn.textContent = '▶️';
    trackProgress.value = 0;
});


// ==========================================
// 6. Built-in Electronic Demo Beat Synthesizer
// ==========================================
let demoTimer = null;
let demoStep = 0;
let isDemoRunning = false;

function playSyntheticKick(time) {
    const osc = audioCtx.createOscillator();
    const gain = audioCtx.createGain();
    osc.frequency.setValueAtTime(150, time);
    osc.frequency.exponentialRampToValueAtTime(38, time + 0.12);
    gain.gain.setValueAtTime(1.0, time);
    gain.gain.exponentialRampToValueAtTime(0.001, time + 0.35);
    osc.connect(gain);
    gain.connect(analyserNode);
    gain.connect(audioCtx.destination);
    osc.start(time);
    osc.stop(time + 0.35);
}

function playSyntheticSnare(time) {
    // Noise buffer
    const bufferSize = audioCtx.sampleRate * 0.18;
    const buffer = audioCtx.createBuffer(1, bufferSize, audioCtx.sampleRate);
    const data = buffer.getChannelData(0);
    for (let i = 0; i < bufferSize; i++) data[i] = Math.random() * 2 - 1;

    const noise = audioCtx.createBufferSource();
    noise.buffer = buffer;
    const filter = audioCtx.createBiquadFilter();
    filter.type = 'highpass';
    filter.frequency.value = 1000;
    const gain = audioCtx.createGain();
    gain.gain.setValueAtTime(0.6, time);
    gain.gain.exponentialRampToValueAtTime(0.001, time + 0.18);

    noise.connect(filter);
    filter.connect(gain);
    gain.connect(analyserNode);
    gain.connect(audioCtx.destination);
    noise.start(time);
}

function startDemoSynth() {
    initAudioContext();
    stopMic();
    audioEl.pause();
    isDemoRunning = true;
    demoStep = 0;
    demoBtn.classList.add('active');
    trackNameEl.textContent = '🎶 ریتم الکترونیک دمو (Club Beat)';
    playerCard.classList.add('active');
    playPauseBtn.textContent = '⏸️';

    const bpm = 124;
    const stepInterval = (60 / bpm) / 4; // 16th notes

    demoTimer = setInterval(() => {
        if (!isDemoRunning) return;
        const now = audioCtx.currentTime;
        const s = demoStep % 16;
        // Kick on 0, 4, 8, 12 (four-on-the-floor)
        if (s % 4 === 0) playSyntheticKick(now);
        // Snare on 4, 12
        if (s === 4 || s === 12) playSyntheticSnare(now);
        demoStep++;
    }, stepInterval * 1000);

    showToast('ریتم تست دمو فعال شد', 'success');
}

function stopDemoSynth() {
    if (demoTimer) {
        clearInterval(demoTimer);
        demoTimer = null;
    }
    isDemoRunning = false;
    demoBtn.classList.remove('active');
}

demoBtn.addEventListener('click', () => {
    if (isDemoRunning) {
        stopDemoSynth();
        playerCard.classList.remove('active');
        showToast('دمو متوقف شد');
    } else {
        startDemoSynth();
    }
});


// ==========================================
// 7. Microphone Input & Error Handling
// ==========================================
let isMicActive = false;

function stopMic() {
    if (micStream) {
        micStream.getTracks().forEach(t => t.stop());
        micStream = null;
    }
    if (micSourceNode) {
        micSourceNode.disconnect();
        micSourceNode = null;
    }
    isMicActive = false;
    micBtn.classList.remove('active');
    micBtn.textContent = '🎤 میکروفون';
}

function startMic() {
    initAudioContext();
    stopDemoSynth();
    audioEl.pause();
    playerCard.classList.remove('active');

    // Check if browser allows mediaDevices on current protocol
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        showToast('مرورگر در حالت آفلاین به میکروفون اجازه دسترسی نمی‌دهد. لطفاً از دکمه «🎵 انتخاب آهنگ» استفاده کنید.', 'error', 5500);
        return;
    }

    navigator.mediaDevices.getUserMedia({ audio: true, video: false }).then(stream => {
        micStream = stream;
        micSourceNode = audioCtx.createMediaStreamSource(stream);
        // Connect to analyser ONLY (do not connect to destination to avoid acoustic feedback screech)
        micSourceNode.connect(analyserNode);
        isMicActive = true;
        micBtn.classList.add('active');
        micBtn.textContent = '🎤 میکروفون فعال';
        showToast('میکروفون متصل شد - فروسیال به صدای محیط واکنش می‌دهد', 'success');
    }).catch(err => {
        console.warn('Microphone error:', err);
        stopMic();
        showToast('دسترسی به میکروفون داده نشد. می‌توانید با دکمه «🎵 انتخاب آهنگ» فایل صوتی پخش کنید.', 'error', 5000);
    });
}

micBtn.addEventListener('click', () => {
    if (isMicActive) {
        stopMic();
        showToast('میکروفون غیرفعال شد');
    } else {
        startMic();
    }
});


// ==========================================
// 8. Theme Switcher
// ==========================================
document.querySelectorAll('.theme-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        currentTheme = btn.dataset.theme;
        document.querySelectorAll('.theme-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
    });
});


// ==========================================
// 9. Multi-Touch / Pointer Interaction
// ==========================================
let touchPos = [0, 0];
let touchActive = false;

function updateTouch(e) {
    const rect = canvas.getBoundingClientRect();
    const nx = ((e.clientX - rect.left) / rect.width) * 2 - 1;
    const ny = -(((e.clientY - rect.top) / rect.height) * 2 - 1);
    const aspect = canvas.width / canvas.height;
    // Map screen-space touch coordinates to shader aspect ratio space
    const px = aspect > 1.0 ? nx * aspect : nx;
    const py = aspect < 1.0 ? ny / aspect : ny;
    touchPos = [px, py];
}

canvas.addEventListener('pointerdown', (e) => {
    touchActive = true;
    updateTouch(e);
});
canvas.addEventListener('pointermove', (e) => {
    if (touchActive) updateTouch(e);
});
window.addEventListener('pointerup', () => { touchActive = false; });
window.addEventListener('pointercancel', () => { touchActive = false; });


// ==========================================
// 10. Main Animation & Render Loop
// ==========================================
let lastFrameTime = performance.now();
const startTime = performance.now();

function render(now) {
    const deltaSec = Math.min((now - lastFrameTime) * 0.001, 0.10);
    lastFrameTime = now;
    const timeSec = (now - startTime) * 0.001;

    // 1. Extract audio features
    const feat = extractAudioFeatures(deltaSec);

    // 2. Step fluid simulation
    updateChoreography(feat, deltaSec);
    packUniforms();

    // 3. Render WebGL Frame
    gl.clearColor(0, 0, 0, 0);
    gl.clear(gl.COLOR_BUFFER_BIT);

    const t = THEMES[currentTheme] || THEMES.ink;
    gl.uniform2f(uResLoc, canvas.width, canvas.height);
    gl.uniform1f(uTimeLoc, timeSec);
    gl.uniform1i(uBlobCountLoc, N_BLOBS);
    gl.uniform4fv(uBlobsLoc, blobs_uniform);
    gl.uniform4fv(uMagnetsLoc, magnets_uniform);
    gl.uniform1f(uSpikeLoc, spike);
    gl.uniform1f(uF0Loc, t.f0);
    gl.uniform3fv(uBodyColorLoc, t.body);
    gl.uniform3fv(uRimColorLoc, t.rim);
    gl.uniform1f(uRimGainLoc, t.rimGain);
    gl.uniform1f(uGlintGainLoc, t.glintGain);
    gl.uniform1f(uShadowAlphaLoc, t.shadow);
    gl.uniform1f(uIridescenceLoc, t.iri);

    gl.drawArrays(gl.TRIANGLES, 0, 6);

    requestAnimationFrame(render);
}
requestAnimationFrame(render);
