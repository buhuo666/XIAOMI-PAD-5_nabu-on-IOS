#!/usr/bin/env python3
"""Check the merged alpha shader against the original eight source-over layers."""
import math
import random
import struct


def f32(value):
    """Round each shader intermediate to Metal's scalar float precision."""
    return struct.unpack('<f', struct.pack('<f', float(value)))[0]


def fract(value):
    value = f32(value)
    return f32(value - math.floor(value))


def marker(uvx, uvy, seconds, layer):
    x = fract(f32(f32(seconds) * f32(0.35)) + f32(f32(layer) * f32(0.117)))
    return 1.0 if abs(f32(uvx) - x) < f32(0.065) and abs(f32(uvy) - f32(0.5)) < f32(0.2) else 0.0


def layer_color(uvx, uvy, seconds, layer):
    m = marker(uvx, uvy, seconds, layer)
    if layer == 0:
        return (f32(f32(0.08) + f32(m * f32(0.8))), f32(f32(uvy) * f32(0.35)),
                f32(f32(0.3) + f32(m * f32(0.4))), f32(1.0))
    return (fract(f32(layer) * f32(0.37)), f32(f32(0.25) + f32(m * f32(0.7))),
            f32(f32(1.0) - f32(uvy) * f32(0.5)), f32(f32(0.08) + f32(m * f32(0.12))))


def source_over(destination, source, alpha):
    return tuple(f32(f32(source[i]) * f32(alpha) + f32(destination[i]) * f32(1.0 - alpha))
                 for i in range(3))


def original(uvx, uvy, seconds):
    out = layer_color(uvx, uvy, seconds, 0)
    for layer in range(1, 8):
        source = layer_color(uvx, uvy, seconds, layer)
        alpha = source[3]
        out = source_over(out, source, alpha) + (f32(1.0),)
    return out


def merged(uvx, uvy, seconds):
    color = layer_color(uvx, uvy, seconds, 0)[:3]
    for layer in range(1, 8):
        source = layer_color(uvx, uvy, seconds, layer)
        alpha = source[3]
        color = source_over(color, source, alpha)
    return color + (f32(1.0),)


def barcode_pixel(frame, pixel_x, width=1600):
    """Model `uint(position.x * 16 / float(width))` in the merged Metal shader."""
    scaled = f32(f32(pixel_x) * f32(16.0) / f32(width))
    bit = min(int(scaled), 15)
    value = f32((frame >> bit) & 1)
    return (value, value, value, f32(1.0))


def merged_fragment(frame, pixel_x, pixel_y, seconds, width=1600, height=2560):
    """Reference the merged shader's full fragment branch, including its barcode."""
    if f32(pixel_y) < f32(64.0):
        return barcode_pixel(frame, pixel_x, width)
    return merged(f32(pixel_x) / f32(width), f32(pixel_y) / f32(height), seconds)


def main():
    random.seed(0xA740)
    checked = 0
    max_error = 0.0
    samples = [(random.random(), random.random(), random.random() * 600.0) for _ in range(20000)]
    # Exercise the strict marker boundaries and phase wrap, which random points
    # almost never hit. Metal's comparisons are strict (<), as in the shader.
    for seconds in (0.0, 1.0 / 0.35, 600.0, 599.999999):
        for layer in range(8):
            center = fract(f32(f32(seconds) * f32(0.35)) + f32(f32(layer) * f32(0.117)))
            for dx in (-f32(0.065), f32(0.065), f32(0.065) + f32(2e-7)):
                samples.append((f32(center + dx), f32(0.5), seconds))
            for dy in (-f32(0.2), f32(0.2), f32(0.2) + f32(2e-7)):
                samples.append((f32(center), f32(0.5 + dy), seconds))
    for uvx, uvy, seconds in samples:
        expected, actual = original(uvx, uvy, seconds), merged(uvx, uvy, seconds)
        error = max(abs(a - b) for a, b in zip(expected, actual))
        max_error = max(max_error, error)
        assert error <= 0.0, (uvx, uvy, seconds, expected, actual, error)
        checked += 1
    # The barcode path bypasses the layer loop and must stay opaque.
    width = 1600
    boundary = [f32(width * cell / 16.0) for cell in range(17)]
    pixels = [0.0, f32(0.5), f32(width - 1.0), *boundary]
    for frame in (0, 1, 0x55AA, 0xFFFFFFFF):
        for pixel_x in pixels:
            expected = barcode_pixel(frame, pixel_x, width)
            actual = merged_fragment(frame, pixel_x, f32(63.999), 0.0, width)
            assert actual == expected, (frame, pixel_x, expected, actual)
    print({"passed": True, "samples": checked, "max_error": max_error,
           "draws_before": 8, "draws_after": 1, "scope": "host mathematical equivalence; Metal rounding and pixel readback remain device checks"})


if __name__ == "__main__":
    main()
