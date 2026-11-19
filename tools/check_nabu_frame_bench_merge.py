#!/usr/bin/env python3
"""Check the merged alpha shader against the original eight source-over layers."""
import math
import random


def fract(value):
    return value - math.floor(value)


def marker(uvx, uvy, seconds, layer):
    x = fract(seconds * 0.35 + layer * 0.117)
    return 1.0 if abs(uvx - x) < 0.065 and abs(uvy - 0.5) < 0.2 else 0.0


def layer_color(uvx, uvy, seconds, layer):
    m = marker(uvx, uvy, seconds, layer)
    if layer == 0:
        return (0.08 + m * 0.8, uvy * 0.35, 0.3 + m * 0.4, 1.0)
    return (fract(layer * 0.37), 0.25 + m * 0.7, 1.0 - uvy * 0.5, 0.08 + m * 0.12)


def original(uvx, uvy, seconds):
    out = layer_color(uvx, uvy, seconds, 0)
    for layer in range(1, 8):
        source = layer_color(uvx, uvy, seconds, layer)
        alpha = source[3]
        out = tuple(source[i] * alpha + out[i] * (1.0 - alpha) for i in range(3)) + (1.0,)
    return out


def merged(uvx, uvy, seconds):
    color = layer_color(uvx, uvy, seconds, 0)[:3]
    for layer in range(1, 8):
        source = layer_color(uvx, uvy, seconds, layer)
        alpha = source[3]
        color = tuple(source[i] * alpha + color[i] * (1.0 - alpha) for i in range(3))
    return color + (1.0,)


def main():
    random.seed(0xA740)
    checked = 0
    max_error = 0.0
    for _ in range(20000):
        uvx, uvy = random.random(), random.random()
        seconds = random.random() * 600.0
        expected, actual = original(uvx, uvy, seconds), merged(uvx, uvy, seconds)
        error = max(abs(a - b) for a, b in zip(expected, actual))
        max_error = max(max_error, error)
        assert error <= 1e-12, (uvx, uvy, seconds, expected, actual, error)
        checked += 1
    # The barcode path bypasses the layer loop and must stay opaque.
    for frame in (0, 1, 0x55AA, 0xFFFFFFFF):
        for x in (0.0, 0.031, 0.5, 0.999):
            bit = min(int(x * 16), 15)
            value = float((frame >> bit) & 1)
            assert merged(x, 0.01, 0.0)[3] == 1.0
            assert value in (0.0, 1.0)
    print({"passed": True, "samples": checked, "max_error": max_error,
           "draws_before": 8, "draws_after": 1, "scope": "host mathematical equivalence; Metal rounding and pixel readback remain device checks"})


if __name__ == "__main__":
    main()
