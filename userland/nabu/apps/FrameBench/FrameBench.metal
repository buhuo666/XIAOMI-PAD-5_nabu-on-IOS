#include <metal_stdlib>
using namespace metal;

struct Parameters {
    uint frame;
    uint layer;
    uint width;
    uint height;
    float seconds;
};

vertex float4 bench_vertex(uint vertexID [[vertex_id]]) {
    const float2 points[] = {float2(-1, -1), float2(3, -1), float2(-1, 3)};
    return float4(points[vertexID], 0, 1);
}

fragment float4 bench_fragment(float4 position [[position]],
                              constant Parameters &p [[buffer(0)]]) {
    const float2 uv = position.xy / float2(p.width, p.height);
    if (position.y < 64) {
        // Sixteen binary cells expose the generated frame identity to a camera.
        const uint bit = min(uint(position.x * 16 / float(p.width)), 15u);
        const float v = float((p.frame >> bit) & 1u);
        return float4(v, v, v, p.layer == 0 ? 1.0f : 0.0f);
    }
    const float x = fract(p.seconds * 0.35f + float(p.layer) * 0.117f);
    const float marker = abs(uv.x - x) < 0.065f && abs(uv.y - 0.5f) < 0.2f ? 1.0f : 0.0f;
    if (p.layer == 0) return float4(0.08f + marker * 0.8f, uv.y * 0.35f, 0.3f + marker * 0.4f, 1);
    return float4(fract(float(p.layer) * 0.37f), 0.25f + marker * 0.7f,
                  1.0f - uv.y * 0.5f, 0.08f + marker * 0.12f);
}
