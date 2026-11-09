// SPDX-License-Identifier: MIT
#include <metal_stdlib>
using namespace metal;

kernel void nabu_compute(device uint *output [[buffer(0)]],
                         constant uint &base [[buffer(1)]],
                         uint index [[thread_position_in_grid]]) {
    output[index] = index * 3u + base;
}

struct NabuVertex {
    float4 position [[position]];
    float4 color;
};

vertex NabuVertex nabu_vertex(device const float2 *positions [[buffer(0)]],
                             device const float4 *colors [[buffer(1)]],
                             uint index [[vertex_id]]) {
    return {float4(positions[index], 0.0f, 1.0f), colors[index]};
}

fragment float4 nabu_fragment(NabuVertex input [[stage_in]]) {
    return input.color;
}
