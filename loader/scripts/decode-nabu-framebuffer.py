#!/usr/bin/env python3
"""Read the current nabu early console using the font from its exact Mach-O."""
from array import array
import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys

WIDTH, HEIGHT, STRIDE, SCALE = 1600, 2560, 1600, 2
WHITE, BLACK = 0xffffffff, 0xff000000


def kernel_layout(image, symbol):
    """Resolve one defined symbol and bounded segments from the exact Mach-O."""
    if len(image) < 32:
        raise ValueError("truncated Mach-O")
    magic, cpu, _, _, count, length, _, _ = struct.unpack_from("<8I", image)
    if magic != 0xfeedfacf or cpu != 0x100000c or length > len(image) - 32:
        raise ValueError("expected a bounded little-endian arm64 Mach-O")
    offset, end = 32, 32 + length
    segments, symtab = [], None
    for _ in range(count):
        if end - offset < 8:
            raise ValueError("truncated Mach-O command")
        command, size = struct.unpack_from("<II", image, offset)
        if size < 8 or size % 8 or size > end - offset:
            raise ValueError("invalid Mach-O command size")
        if command == 0x19:
            if size < 72:
                raise ValueError("truncated segment")
            vmaddr, vmsize, fileoff, filesize = struct.unpack_from("<4Q", image, offset + 24)
            if fileoff > len(image) or filesize > len(image) - fileoff:
                raise ValueError("segment exceeds file")
            # XNU's __CTF can contain file-only metadata with vmsize zero.
            segments.append((vmaddr, vmsize, fileoff, min(vmsize, filesize)))
        elif command == 2:
            if size != 24 or symtab is not None:
                raise ValueError("invalid or duplicate symbol table")
            symtab = struct.unpack_from("<4I", image, offset + 8)
        offset += size
    if offset != end or symtab is None:
        raise ValueError("missing symbol table or inconsistent commands")
    symoff, nsyms, stroff, strsize = symtab
    if symoff > len(image) or nsyms > (len(image) - symoff) // 16:
        raise ValueError("symbol table exceeds file")
    if stroff > len(image) or strsize > len(image) - stroff:
        raise ValueError("string table exceeds file")
    matches = []
    for index in range(nsyms):
        nameoff, kind, section, _, address = struct.unpack_from("<IBBHQ", image, symoff + index * 16)
        if kind & 0xe0 or kind & 0xe != 0xe or not section:
            continue
        if nameoff >= strsize:
            raise ValueError("symbol name exceeds string table")
        nameend = image.find(b"\0", stroff + nameoff, stroff + strsize)
        if nameend == -1:
            raise ValueError("unterminated symbol name")
        if image[stroff + nameoff:nameend] == symbol.encode("ascii"):
            matches.append(address)
    if len(matches) != 1:
        raise ValueError(f"expected exactly one defined {symbol}")
    if not any(vmaddr <= matches[0] < vmaddr + vmsize for vmaddr, vmsize, _, _ in segments):
        raise ValueError(f"{symbol} is outside mapped segments")
    return segments, matches[0]


def kernel_symbol_offset(image, symbol):
    segments, address = kernel_layout(image, symbol)
    return address - min(vmaddr for vmaddr, vmsize, _, _ in segments if vmsize)


def kernel_font(image):
    segments, address = kernel_layout(image, "_iso_font")
    for vmaddr, _, fileoff, filesize in segments:
        relative = address - vmaddr
        if 0 <= relative and relative + 4096 <= filesize:
            return image[fileoff + relative:fileoff + relative + 4096]
    raise ValueError("_iso_font is not backed by 4096 file bytes")


def checkpoint_stages(raw):
    if len(raw) != 4:
        raise ValueError("expected a four-byte early-stage mask")
    mask, = struct.unpack("<I", raw)
    if mask & ~((1 << 21) - 1):
        raise ValueError("early-stage mask contains unknown stage bits")
    return mask, [stage for stage in range(1, 21) if mask & (1 << stage)]


def decode(raw, font, full_console=False):
    if len(raw) != STRIDE * HEIGHT * 4 or len(font) != 4096:
        raise ValueError("expected the fixed 1600x2560 BGRA32 framebuffer and 4096-byte font")
    pixels = array("I", raw)
    if sys.byteorder != "little":
        pixels.byteswap()
    glyphs = {}
    for char in range(32, 127):
        glyphs.setdefault(font[char * 16:(char + 1) * 16], chr(char))
    # The bottom 32 scanlines contain stage bands, not console cells.
    rows, unknown = [], 0
    for row in range(HEIGHT // 32 if full_console else (HEIGHT - 32) // 32):
        text, rendered = [], False
        for col in range(WIDTH // 16):
            glyph = bytearray()
            valid = True
            for gy in range(16):
                bits = 0
                for gx in range(8):
                    pos = (row * 32 + gy * SCALE) * STRIDE + col * 16 + gx * SCALE
                    color = pixels[pos]
                    if color not in (BLACK, WHITE) or any(
                            pixels[pos + dy * STRIDE + dx] != color
                            for dy in range(SCALE) for dx in range(SCALE)):
                        valid = False
                        break
                    bits |= int(color == WHITE) << gx
                if not valid:
                    break
                glyph.append(bits)
            if valid:
                rendered = True
                encoded = bytes(glyph)
                char = glyphs.get(encoded, "?")
                unknown += encoded not in glyphs
                text.append(char)
            else:
                text.append(" ")
        line = "".join(text).rstrip()
        if rendered and line:
            rows.append({"row": row, "text": line})
    return {
        "framebuffer_sha256": hashlib.sha256(raw).hexdigest(),
        "font_sha256": hashlib.sha256(font).hexdigest(),
        "decoded_rows": rows, "unrecognized_rendered_cells": unknown,
        "physical_row_order_only": True,
        "limits": "Exact glyph matches only; console wrap may reorder older lines. This is not a boot verdict.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kernel", type=Path, required=True)
    parser.add_argument("--framebuffer", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--full-console", action="store_true",
                        help="include the last row after normal fbcon has replaced the stage bands")
    args = parser.parse_args()
    try:
        image = args.kernel.read_bytes()
        report = decode(args.framebuffer.read_bytes(), kernel_font(image), args.full_console)
    except (OSError, ValueError, struct.error) as error:
        parser.exit(2, f"framebuffer decode failed: {error}\n")
    report["kernel_sha256"] = hashlib.sha256(image).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("\n".join(row["text"] for row in report["decoded_rows"]))


if __name__ == "__main__":
    main()
