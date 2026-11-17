#version 330 core

in vec2 vUV;
in vec2 vPos;

out vec4 fragColor;

// Uniforms
uniform vec2 uResolution;
uniform float uTime;
uniform int uBlobCount;
uniform vec4 uBlobs[64];      // x, y, r, weight
uniform vec4 uMagnets[19];    // x, y, strength, 0
uniform float uSpike;
uniform float uEnvRot;
uniform float uEditMode;
uniform int uDebugBg;         // 0=none, 1=dark, 2=light, 3=checker
uniform int uRenderMode;      // 0=heightfield (default), 1=raymarch

// Theme Uniforms
uniform float uF0;
uniform vec3 uBodyColor;
uniform vec3 uRimColor;
uniform float uRimGain;
uniform float uGlintGain;
uniform float uShadowAlpha;
uniform float uIridescence;

#define PI 3.141592653589793
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

    // Support factor: 1.0 / sqrt(1.0 - pow(0.35, 1.0/3.0)) ~= 1.84020
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
    const float a = 2.51;
    const float b = 0.03;
    const float c = 2.43;
    const float d = 0.59;
    const float e = 0.14;
    return clamp((x * (a * x + b)) / (x * (c * x + d) + e), 0.0, 1.0);
}

// Linear to sRGB
vec3 linearToSRGB(vec3 color) {
    return pow(color, vec3(1.0 / 2.2));
}

// Procedural HDR Studio Environment with fwidth anti-aliased light box edges
vec3 studioEnvironment(vec3 r, float edge_factor) {
    // 1. Key Softbox: Upper-left overhead (large rectangular area light)
    vec3 keyDir = normalize(vec3(-0.45, 0.65, 0.60));
    float keyDot = dot(r, keyDir);
    float fwKey = max(fwidth(keyDot), 0.004);
    float keySoftbox = smoothstep(0.82 - fwKey, 0.98 + fwKey, keyDot) * 3.8;

    // 2. Strip Rim-Box: Upper-right edge
    vec3 rimDir = normalize(vec3(0.68, 0.52, 0.51));
    float rimDot = dot(r, rimDir);
    float fwRim = max(fwidth(rimDot), 0.004);
    float rimBox = smoothstep(0.89 - fwRim, 0.99 + fwRim, rimDot) * 2.6;

    // 3. Pinpoint Spotlight: produces razor-sharp glossy glints
    vec3 spotDir = normalize(vec3(-0.15, 0.40, 0.90));
    float spotDot = max(dot(r, spotDir), 0.0);
    float spotGlint = pow(spotDot, 256.0) * 12.0;

    // 4. Studio Cyclorama Floor Bounce: illuminates the steep outer meniscus edge
    // Gated by edge_factor so only the perimeter silhouette is illuminated on black backgrounds
    float floorBounce = smoothstep(0.15, -0.40, r.z) * edge_factor;
    vec3 floorColor = vec3(0.40, 0.43, 0.46) * 2.2;

    // Deep obsidian ambient
    vec3 ambient = vec3(0.005, 0.006, 0.008);

    vec3 env = ambient + vec3(1.0, 0.98, 0.95) * keySoftbox + vec3(0.92, 0.96, 1.0) * rimBox + vec3(1.0) * spotGlint + floorColor * floorBounce;
    return env;
}

// Thin-film Iridescence
vec3 evalIridescence(float cosTheta, float thickness) {
    vec3 phase = vec3(0.0, 2.0, 4.0) + 7.0 * (1.0 - cosTheta) + 5.0 * thickness;
    return 0.5 + 0.5 * cos(phase);
}

// 3D SDF for Raymarch Stretch Mode
float sdfScene(vec3 p) {
    float minDist = 1e5;
    for (int i = 0; i < 64; ++i) {
        if (i >= uBlobCount) break;
        vec4 b = uBlobs[i];
        float dist = length(p - vec3(b.xy, 0.0)) - b.z;
        float h = clamp(0.5 + 0.5 * (minDist - dist) / 0.12, 0.0, 1.0);
        minDist = mix(minDist, dist, h) - 0.12 * h * (1.0 - h);
    }
    return minDist;
}

void main() {
    // Map screen coordinates to unit square [-1, 1] preserving aspect ratio
    float aspect = uResolution.x / uResolution.y;
    vec2 p = vPos;
    if (aspect > 1.0) {
        p.x *= aspect;
    } else {
        p.y /= aspect;
    }

    // Raymarching Stretch Mode
    if (uRenderMode == 1) {
        vec3 ro = vec3(p, -1.2);
        vec3 rd = vec3(0.0, 0.0, 1.0);
        float t_dist = 0.0;
        bool hit = false;
        for (int step = 0; step < 48; ++step) {
            vec3 current_pos = ro + rd * t_dist;
            float d = sdfScene(current_pos);
            if (d < 0.002) { hit = true; break; }
            t_dist += d;
            if (t_dist > 2.5) break;
        }
        if (hit) {
            vec3 hitPos = ro + rd * t_dist;
            vec2 eps = vec2(0.003, 0.0);
            vec3 nor = normalize(vec3(
                sdfScene(hitPos + eps.xyy) - sdfScene(hitPos - eps.xyy),
                sdfScene(hitPos + eps.yxy) - sdfScene(hitPos - eps.yxy),
                sdfScene(hitPos + eps.yyx) - sdfScene(hitPos - eps.yyx)
            ));
            vec3 ref = reflect(-vec3(0.0, 0.0, 1.0), nor);
            vec3 envRad = studioEnvironment(ref, 1.0);
            vec3 col = uBodyColor + envRad * uF0 * uGlintGain;
            vec3 srgb = linearToSRGB(tonemapACES(col));
            fragColor = vec4(srgb, 1.0);
            return;
        } else {
            fragColor = vec4(0.0);
            return;
        }
    }

    // 1. Evaluate Metaball Potential Field
    float f = 0.0;
    vec2 grad_f = vec2(0.0);
    float r_local = 0.1;
    evalMetaballs(p, f, grad_f, r_local);

    // 2. Rosensweig Hexagonal Spikes
    // Compute magnetic field proxy B(p)
    float B = 0.0;
    for (int k = 0; k < 19; ++k) {
        vec4 mag = uMagnets[k];
        if (mag.z <= 0.001) continue;
        vec2 m_pos = mag.xy;
        float d2 = dot(p - m_pos, p - m_pos);
        B += mag.z * exp(-d2 / 0.12);
    }

    // Gate activation: gated by magnetic strength and fluid presence
    float g = smoothstep(0.25, 0.80, B) * smoothstep(0.60 * ISO_T, 1.30 * ISO_T, f);

    // Hex lattice coordinate domain-warping
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
        // Smooth C1 Hermite falloff for rounded, glossy organic liquid crests (no sharp facets)
        float q = clamp(1.0 - d_s / rho, 0.0, 1.0);
        s = q * q * (3.0 - 2.0 * q);
        grad_s = -6.0 * q * (1.0 - q) * (d_vec / max(d_s, 1e-5)) / rho;
    }

    float A_spike = 0.12;
    float spike_disp = A_spike * uSpike * g * s;
    float f_total = f + spike_disp;
    vec2 grad_total = grad_f + A_spike * uSpike * (grad_s * g);

    // 3. Signed Distance & Analytic Anti-Aliased Alpha
    float grad_len = max(length(grad_total), 1e-4);
    float sd = (f_total - ISO_T) / grad_len;
    float pixel_size = 2.0 / min(uResolution.x, uResolution.y);
    float alpha = clamp(0.5 + sd / pixel_size, 0.0, 1.0);

    // 4. 2.5D Meniscus Height-Field and Normal
    vec3 n = vec3(0.0, 0.0, 1.0);
    float h = 0.0;
    if (f_total > ISO_T) {
        float H_s = 0.45 * sqrt(clamp(r_local, 0.02, 0.35));
        float root_f = sqrt(max(f_total - ISO_T, 1e-5));
        h = H_s * root_f;
        vec2 grad_h = (H_s * grad_total) / (2.0 * max(root_f, 1e-3));

        // High frequency capillary micro-ripple
        float r_len = length(p);
        float ripple_k = 65.0;
        float ripple_grad = 0.0025 * ripple_k * cos(ripple_k * r_len - 8.0 * uTime);
        grad_h += ripple_grad * (p / max(r_len, 1e-4));

        float slopeGain = 1.65;
        n = normalize(vec3(-grad_h * slopeGain, 1.0));
    }

    // 5. Studio HDR Lighting & Shading
    vec3 v = vec3(0.0, 0.0, 1.0);
    vec3 r_vec = reflect(-v, n);

    // Rotate reflection XY
    float c_rot = cos(uEnvRot);
    float s_rot = sin(uEnvRot);
    vec3 r_rot = vec3(
        r_vec.x * c_rot - r_vec.y * s_rot,
        r_vec.x * s_rot + r_vec.y * c_rot,
        r_vec.z
    );

    float NdotV = max(dot(n, v), 0.0);
    // Schlick Fresnel
    float F = uF0 + (1.0 - uF0) * pow(1.0 - NdotV, 5.0);

    // Outer perimeter edge factor for rim lighting & floor bounce
    float edge_factor = smoothstep(1.75 * ISO_T, 1.0 * ISO_T, f_total);

    // Sample Studio HDR environment
    vec3 envRadiance = studioEnvironment(r_rot, edge_factor);

    // Base body color + specular reflections
    vec3 body = uBodyColor * (1.0 - F);
    vec3 spec = envRadiance * F * uGlintGain;

    // Outer rim illumination (gated to perimeter edge)
    float rimWeight = pow(1.0 - NdotV, 3.2) * edge_factor;
    vec3 rim = rimWeight * uRimColor * uRimGain;

    // Thin film iridescence
    if (uIridescence > 0.0) {
        vec3 iriColor = evalIridescence(NdotV, h);
        spec += iriColor * uIridescence * F * 1.5;
    }

    vec3 fluid_hdr = body + spec + rim;
    vec3 fluid_tonemapped = tonemapACES(fluid_hdr);
    vec3 fluid_srgb = linearToSRGB(fluid_tonemapped);

    // Triangular dither to eliminate color banding
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
    vec3 final_rgb = clamp(fluid_srgb * alpha, 0.0, final_alpha); // Guarantee 0 <= rgb <= alpha

    // 8. Edit Mode Visual Feedback
    if (uEditMode > 0.5) {
        float r_dist = length(p);
        float ring = abs(r_dist - 0.92);
        float dash = sin(atan(p.y, p.x) * 24.0);
        if (ring < 0.008 && dash > 0.0) {
            vec3 editRingColor = vec3(0.3, 0.8, 1.0);
            final_rgb += editRingColor * 0.8;
            final_alpha = max(final_alpha, 0.8);
        }
    }

    // 9. Debug Background Composition
    if (uDebugBg > 0) {
        vec3 bg = vec3(0.0);
        if (uDebugBg == 1) {
            bg = vec3(0.08, 0.08, 0.09); // Dark
        } else if (uDebugBg == 2) {
            bg = vec3(0.92, 0.92, 0.94); // Light
        } else if (uDebugBg == 3) {
            // Checkerboard
            vec2 check = floor(gl_FragCoord.xy / 24.0);
            float c = mod(check.x + check.y, 2.0);
            bg = mix(vec3(0.2), vec3(0.65), c);
        }
        // Alpha composite
        final_rgb = final_rgb + bg * (1.0 - final_alpha);
        final_alpha = 1.0;
    }

    fragColor = vec4(final_rgb, final_alpha);
}
