"""Lossless zero-page packing for private board snapshots carried in the ADT."""
import struct

PAGE = 4096


def pack(data):
    assert data and len(data) % PAGE == 0
    pages = [(at, data[at:at+PAGE]) for at in range(0, len(data), PAGE) if any(data[at:at+PAGE])]
    return struct.pack('<4sIII', b'NRF1', len(data), PAGE, len(pages)) + b''.join(
        struct.pack('<I', at) + value for at, value in pages)


def unpack(data):
    magic, size, page, count = struct.unpack_from('<4sIII', data)
    assert magic == b'NRF1' and page == PAGE and len(data) == 16 + count * (4+PAGE)
    output = bytearray(size)
    for i in range(count):
        at = 16+i*(4+PAGE); offset, = struct.unpack_from('<I', data, at)
        assert offset % PAGE == 0 and offset + PAGE <= size
        output[offset:offset+PAGE] = data[at+4:at+4+PAGE]
    return bytes(output)
