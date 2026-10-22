#!/usr/bin/env python3
"""Check bounded font extraction and exact early-console glyph decoding."""
import importlib.util
from pathlib import Path
import struct
import unittest

spec = importlib.util.spec_from_file_location(
    "framebuffer", Path(__file__).with_name("decode-nabu-framebuffer.py"))
fb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fb)


def fixture():
    font = bytearray(4096)
    font[65 * 16:66 * 16] = bytes([0x18, 0x24, 0x42, 0x7e, 0x42] + [0] * 11)
    base, fileoff = 0xfffffe0007004000, 0x1000
    symoff, stroff = fileoff + len(font), fileoff + len(font) + 16
    strings = b"\0_iso_font\0"
    image = bytearray(stroff + len(strings))
    struct.pack_into("<8I", image, 0, 0xfeedfacf, 0x100000c, 0, 2, 2, 96, 0, 0)
    struct.pack_into("<II16s4Q4I", image, 32, 0x19, 72, b"__DATA",
                     base, len(font), fileoff, len(font), 3, 3, 0, 0)
    struct.pack_into("<6I", image, 104, 2, 24, symoff, 1, stroff, len(strings))
    image[fileoff:fileoff + len(font)] = font
    struct.pack_into("<IBBHQ", image, symoff, 1, 0xf, 1, 0, base)
    image[stroff:] = strings
    return bytes(image), bytes(font)


class FramebufferTests(unittest.TestCase):
    def test_persistent_checkpoints(self):
        mask = (1 << 1) | (1 << 9) | (1 << 20)
        self.assertEqual(fb.checkpoint_stages(struct.pack("<I", mask)), (mask, [1, 9, 20]))
        for raw in (b"", bytes(3), bytes(5), struct.pack("<I", 1 << 31)):
            with self.assertRaises(ValueError):
                fb.checkpoint_stages(raw)

    def test_font_comes_from_file_backed_symbol(self):
        image, font = fixture()
        self.assertEqual(fb.kernel_font(image), font)
        self.assertEqual(fb.kernel_symbol_offset(image, "_iso_font"), 0)
        with self.assertRaises(ValueError):
            fb.kernel_symbol_offset(image, "_absent")
        metadata = bytearray(image)
        struct.pack_into("<II", metadata, 16, 3, 168)
        struct.pack_into("<II16s4Q4I", metadata, 128, 0x19, 72, b"__CTF",
                         0, 0, 0, 16, 0, 0, 0, 0)
        self.assertEqual(fb.kernel_font(metadata), font)
        for broken in (b"", image[:31], image[:100], image[:-1]):
            with self.subTest(size=len(broken)), self.assertRaises(ValueError):
                fb.kernel_font(broken)
        broken = bytearray(image)
        struct.pack_into("<I", broken, 108, 0)
        with self.assertRaises(ValueError):
            fb.kernel_font(broken)

    def test_decode_requires_exact_scaled_pixels(self):
        _, font = fixture()
        raw = bytearray(fb.STRIDE * fb.HEIGHT * 4)
        for gy in range(16):
            for gx in range(8):
                color = fb.WHITE if font[65 * 16 + gy] & (1 << gx) else fb.BLACK
                for dy in range(2):
                    for dx in range(2):
                        struct.pack_into("<I", raw, ((gy * 2 + dy) * fb.STRIDE + gx * 2 + dx) * 4, color)
        report = fb.decode(raw, font)
        self.assertEqual(report["decoded_rows"], [{"row": 0, "text": "A"}])
        raw[4:8] = b"\0" * 4
        self.assertEqual(fb.decode(raw, font)["decoded_rows"], [])
        with self.assertRaises(ValueError):
            fb.decode(raw[:-1], font)


if __name__ == "__main__":
    unittest.main()
