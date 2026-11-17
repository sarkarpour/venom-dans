#version 330 core

layout(location = 0) in vec2 inPosition;

out vec2 vUV;
out vec2 vPos;

void main() {
    vUV = inPosition * 0.5 + 0.5;
    vPos = inPosition;
    gl_Position = vec4(inPosition, 0.0, 1.0);
}
