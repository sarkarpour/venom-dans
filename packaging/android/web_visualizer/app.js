// FerroWidget Android WebGL 2.0 Visualizer
const canvas = document.getElementById('glcanvas');
const gl = canvas.getContext('webgl2', { alpha: true, premultipliedAlpha: true });

if (!gl) {
    alert('WebGL 2.0 is not supported on this browser/device.');
}

// Fullscreen canvas resizing with High-DPI support
function resize() {
    const dpr = Math.min(window.devicePixelRatio || 1, 2.0);
    canvas.width = window.innerWidth * dpr;
    canvas.height = window.innerHeight * dpr;
    gl.viewport(0, 0, canvas.width, canvas.height);
}
window.addEventListener('resize', resize);
resize();

// Shaders
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
uniform vec4 uBlobs[64];
uniform vec4 uMagnets[19];
uniform float uSpike;
uniform float uF0;
uniform vec3 uBodyColor;
uniform vec3 uRimColor;
uniform float uRimGain;
uniform float uGlintGain;
uniform float uShadowAlpha;
uniform float uIridescence;

#define ISO_T 0.35

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

vec3 tonemapACES(vec3 x) {
    const float a = 2.51, b = 0.03, c = 2.43, d = 0.59, e = 0.14;
    return clamp((x * (a * x + b)) / (x * (c * x + d) + e), 0.0, 1.0);
}

vec3 studioEnvironment(vec3 r, float edge_factor) {
    vec3 keyDir = normalize(vec3(-0.45, 0.65, 0.60));
    float keySoftbox = smoothstep(0.82, 0.98, dot(r, keyDir)) * 3.8;

    vec3 rimDir = normalize(vec3(0.68, 0.52, 0.51));
    float rimBox = smoothstep(0.89, 0.99, dot(r, rimDir)) * 2.6;

    vec3 spotDir = normalize(vec3(-0.15, 0.40, 0.90));
    float spotGlint = pow(max(dot(r, spotDir), 0.0), 256.0) * 12.0;

    float floorBounce = (1.0 - smoothstep(-0.40, 0.15, r.z)) * edge_factor;
    vec3 floorColor = vec3(0.40, 0.43, 0.46) * 2.2;

    return vec3(0.005) + vec3(1.0, 0.98, 0.95) * keySoftbox + vec3(0.92, 0.96, 1.0) * rimBox + vec3(1.0) * spotGlint + floorColor * floorBounce;
}

vec3 evalIridescence(float cosTheta, float thickness) {
    vec3 phase = vec3(0.0, 2.0, 4.0) + 7.0 * (1.0 - cosTheta) + 5.0 * thickness;
    return 0.5 + 0.5 * cos(phase);
}

void main() {
    float aspect = uResolution.x / uResolution.y;
    vec2 p = vPos;
    if (aspect > 1.0) p.x *= aspect; else p.y /= aspect;

    float f = 0.0;
    vec2 grad_f = vec2(0.0);
    float r_local = 0.1;
    evalMetaballs(p, f, grad_f, r_local);

    float grad_len = max(length(grad_f), 1e-4);
    float sd = (f - ISO_T) / grad_len;
    float pixel_size = 2.0 / min(uResolution.x, uResolution.y);
    float alpha = clamp(0.5 + sd / pixel_size, 0.0, 1.0);

    vec3 n = vec3(0.0, 0.0, 1.0);
    float h = 0.0;
    if (f > ISO_T) {
        float H_s = 0.45 * sqrt(clamp(r_local, 0.02, 0.35));
        float root_f = sqrt(max(f - ISO_T, 1e-5));
        h = H_s * root_f;
        vec2 grad_h = (H_s * grad_f) / (2.0 * max(root_f, 1e-3));
        n = normalize(vec3(-grad_h * 1.65, 1.0));
    }

    vec3 v = vec3(0.0, 0.0, 1.0);
    vec3 r_vec = reflect(-v, n);
    float NdotV = max(dot(n, v), 0.0);
    float F = uF0 + (1.0 - uF0) * pow(1.0 - NdotV, 5.0);
    float edge_factor = 1.0 - smoothstep(1.0 * ISO_T, 1.75 * ISO_T, f);

    vec3 envRad = studioEnvironment(r_vec, edge_factor);
    vec3 body = uBodyColor * (1.0 - F);
    vec3 spec = envRad * F * uGlintGain;
    if (uIridescence > 0.0) {
        vec3 iriColor = evalIridescence(NdotV, h);
        spec += iriColor * uIridescence * F * 1.5;
    }
    float rimWeight = pow(1.0 - NdotV, 3.2) * edge_factor;
    vec3 rim = rimWeight * uRimColor * uRimGain;

    vec3 fluid_srgb = pow(tonemapACES(body + spec + rim), vec3(1.0 / 2.2));

    // Circular containment falloff: eliminates rectangular clipping
    float r_screen = length(p);
    float edge_guard = 1.0 - smoothstep(0.82, 0.92, r_screen);
    float final_alpha = alpha * edge_guard;
    vec3 final_rgb = fluid_srgb * final_alpha;

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
gl.useProgram(prog);

// Quad
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

// Physics State (64 blobs)
const N_BLOBS = 64;
const pos = new Float32Array(N_BLOBS * 2);
const vel = new Float32Array(N_BLOBS * 2);
const r = new Float32Array(N_BLOBS);
const r0 = new Float32Array(N_BLOBS);
const weights = new Float32Array(N_BLOBS);
const blobsUniform = new Float32Array(N_BLOBS * 4);

// Initialize droplets
for (let i = 0; i < N_BLOBS; i++) {
    const isCore = i < 6;
    const isSat = i >= 6 && i < 28;
    const baseR = isCore ? (0.11 + Math.random() * 0.04) : (isSat ? (0.06 + Math.random() * 0.03) : (0.03 + Math.random() * 0.02));
    r0[i] = baseR;
    r[i] = baseR;
    weights[i] = isCore ? 1.0 : (isSat ? 0.9 : 0.78);
    const angle = Math.random() * Math.PI * 2;
    const dist = isCore ? (Math.random() * 0.05) : (0.15 + Math.random() * 0.35);
    pos[i * 2] = Math.cos(angle) * dist;
    pos[i * 2 + 1] = Math.sin(angle) * dist;
}

// Uniform Locations
const uRes = gl.getUniformLocation(prog, 'uResolution');
const uTime = gl.getUniformLocation(prog, 'uTime');
const uBlobCount = gl.getUniformLocation(prog, 'uBlobCount');
const uBlobs = gl.getUniformLocation(prog, 'uBlobs');
const uSpike = gl.getUniformLocation(prog, 'uSpike');
const uF0 = gl.getUniformLocation(prog, 'uF0');
const uBodyColor = gl.getUniformLocation(prog, 'uBodyColor');
const uRimColor = gl.getUniformLocation(prog, 'uRimColor');
const uRimGain = gl.getUniformLocation(prog, 'uRimGain');
const uGlintGain = gl.getUniformLocation(prog, 'uGlintGain');
const uIridescence = gl.getUniformLocation(prog, 'uIridescence');

// Audio Context & Mic
let audioCtx = null;
let analyser = null;
let audioData = null;
let micEnergy = 0.0;

function setupAudio() {
    if (audioCtx) return;
    navigator.mediaDevices.getUserMedia({ audio: true }).then(stream => {
        audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        const src = audioCtx.createMediaStreamSource(stream);
        analyser = audioCtx.createAnalyser();
        analyser.fftSize = 256;
        src.connect(analyser);
        audioData = new Uint8Array(analyser.frequencyBinCount);
        document.getElementById('mic-btn').textContent = '🎤 Mic Active';
    }).catch(err => {
        console.warn('Microphone access denied:', err);
    });
}
document.getElementById('mic-btn').addEventListener('click', setupAudio);

// Theme buttons
document.querySelectorAll('.theme-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        currentTheme = btn.dataset.theme;
        document.querySelectorAll('.theme-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
    });
});

// Touch / Mouse interaction
let touchPos = [0, 0];
let touchActive = false;
canvas.addEventListener('pointerdown', (e) => {
    touchActive = true;
    updateTouch(e);
});
canvas.addEventListener('pointermove', (e) => {
    if (touchActive) updateTouch(e);
});
window.addEventListener('pointerup', () => { touchActive = false; });

function updateTouch(e) {
    const rect = canvas.getBoundingClientRect();
    const nx = ((e.clientX - rect.left) / rect.width) * 2 - 1;
    const ny = -(((e.clientY - rect.top) / rect.height) * 2 - 1);
    touchPos = [nx, ny];
}

// Animation Loop
let startTime = performance.now();
function render(now) {
    const timeSec = (now - startTime) * 0.001;
    const dt = 1.0 / 60.0;

    // Read mic
    let bass = 0.0;
    if (analyser && audioData) {
        analyser.getByteFrequencyData(audioData);
        let sum = 0;
        for (let i = 0; i < 8; i++) sum += audioData[i];
        bass = (sum / 8.0) / 255.0;
    } else {
        // Organic breathing synthesis
        bass = 0.25 + 0.25 * Math.sin(timeSec * 2.8) * Math.cos(timeSec * 1.4);
    }

    // Step physics
    const targetX = touchActive ? touchPos[0] * 0.6 : 0;
    const targetY = touchActive ? touchPos[1] * 0.6 : 0;

    for (let i = 0; i < N_BLOBS; i++) {
        let px = pos[i * 2];
        let py = pos[i * 2 + 1];

        // Central pull to target
        const dx = targetX - px;
        const dy = targetY - py;
        const d = Math.sqrt(dx * dx + dy * dy) + 1e-4;
        const pull = (i < 6 ? 2.5 : 0.8) * (1.0 + bass * 1.5);
        vel[i * 2] += (dx / d) * pull * dt;
        vel[i * 2 + 1] += (dy / d) * pull * dt;

        // Swirl
        const sDirX = -py / (Math.sqrt(px * px + py * py) + 1e-4);
        const sDirY = px / (Math.sqrt(px * px + py * py) + 1e-4);
        vel[i * 2] += sDirX * (0.8 + bass * 1.2) * dt;
        vel[i * 2 + 1] += sDirY * (0.8 + bass * 1.2) * dt;

        // Drag
        vel[i * 2] *= 0.94;
        vel[i * 2 + 1] *= 0.94;

        pos[i * 2] += vel[i * 2] * dt;
        pos[i * 2 + 1] += vel[i * 2 + 1] * dt;

        // Boundary containment (< 0.75)
        const pDist = Math.sqrt(pos[i * 2]**2 + pos[i * 2 + 1]**2);
        const maxDist = 0.72 - r[i] * 1.84;
        if (pDist > maxDist) {
            pos[i * 2] = (pos[i * 2] / pDist) * maxDist;
            pos[i * 2 + 1] = (pos[i * 2 + 1] / pDist) * maxDist;
            vel[i * 2] *= -0.3;
            vel[i * 2 + 1] *= -0.3;
        }

        // Pack uniforms
        blobsUniform[i * 4] = pos[i * 2];
        blobsUniform[i * 4 + 1] = pos[i * 2 + 1];
        blobsUniform[i * 4 + 2] = r0[i] * (1.0 + 0.15 * bass);
        blobsUniform[i * 4 + 3] = weights[i];
    }

    // Set uniforms
    gl.clearColor(0, 0, 0, 0);
    gl.clear(gl.COLOR_BUFFER_BIT);

    const t = THEMES[currentTheme];
    gl.uniform2f(uRes, canvas.width, canvas.height);
    gl.uniform1f(uTime, timeSec);
    gl.uniform1i(uBlobCount, N_BLOBS);
    gl.uniform4fv(uBlobs, blobsUniform);
    gl.uniform1f(uSpike, bass * 0.5);
    gl.uniform1f(uF0, t.f0);
    gl.uniform3fv(uBodyColor, t.body);
    gl.uniform3fv(uRimColor, t.rim);
    gl.uniform1f(uRimGain, t.rimGain);
    gl.uniform1f(uGlintGain, t.glintGain);
    gl.uniform1f(uIridescence, t.iri);

    gl.drawArrays(gl.TRIANGLES, 0, 6);
    requestAnimationFrame(render);
}
requestAnimationFrame(render);
