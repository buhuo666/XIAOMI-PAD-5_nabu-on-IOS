#!/usr/bin/env python3
"""Generate the eight-core ADT consumed by the project's patched XNU 8796."""
import argparse
import hashlib
import json
from pathlib import Path
import secrets
import struct
import uuid
import zlib

U32 = lambda x: struct.pack('<I', x)
U64 = lambda x: struct.pack('<Q', x)
STR = lambda x: x.encode('ascii') + b'\0'
CHECKPOINTS = (0, *range(1, 6), *range(10, 22), *range(30, 36), *range(40, 45))
DEFAULT_CHECKPOINT = 12


def platform_uuid_from_soc(identity):
    """Stable port UUID derived from this board's real Qualcomm identity."""
    soc_id, serial = identity['soc_id'], identity['serial_number']
    if not isinstance(soc_id, int) or not isinstance(serial, int) or soc_id <= 0 or serial <= 0:
        raise ValueError('A nonzero SoC id and serial from Android are required')
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f'nabu-platform://soc/{soc_id}/serial/{serial}'))


def usb_serial_from_platform_uuid(platform_uuid):
    """Stable board identifier in AMDS's accepted 40-hex record-name format."""
    return hashlib.sha1(b'nabu-usb:' + uuid.UUID(platform_uuid).bytes).hexdigest()


class Node:
    def __init__(self, name, props=None, children=()):
        self.props = {'name': STR(name), **(props or {})}
        self.children = list(children)

    def encode(self):
        data = U32(len(self.props)) + U32(len(self.children))
        for key, value in self.props.items():
            key = key.encode('ascii')
            assert 0 < len(key) < 32
            data += key.ljust(32, b'\0') + U32(len(value)) + value
            data += bytes(-len(value) % 4)
        return data + b''.join(c.encode() for c in self.children)


def nvram():
    bank = bytearray(8192)
    def header(offset, sig, length, name):
        data = bytearray(struct.pack('<BBH12s', sig, 0, length // 16, name.encode()))
        checksum = sum(data)
        while checksum > 255:
            checksum = (checksum & 255) + (checksum >> 8)
        data[1] = checksum
        bank[offset:offset + 16] = data
    header(0, 0x5a, 32, 'nvram')
    header(32, 0x70, len(bank) - 32, 'common')
    struct.pack_into('<I', bank, 20, 1)
    struct.pack_into('<I', bank, 16, zlib.adler32(bank[20:]))
    return bytes(bank)


def validate_wifi_mac(value):
    """Accept the six binary octets of a nonzero unicast Wi-Fi address."""
    if not isinstance(value, bytes) or len(value) != 6 or not any(value) or value[0] & 1:
        raise ValueError('Wi-Fi MAC must be six binary octets, nonzero and unicast')
    return value


def validate_userland_serial(value):
    """An explicit compatibility label; never infer it from an attached device."""
    if not isinstance(value, str) or not 1 <= len(value) <= 32 or not value.isascii() or not value.isalnum():
        raise ValueError('Compatibility serial must contain 1-32 ASCII letters/digits')
    return value


def make_tree(seed, checkpoint=DEFAULT_CHECKPOINT, bootstrap=False, wifi_mac=None,
              userland_model=None, userland_serial=None, touch_firmware=None, image4_nonce_key=None,
              rtc_offset=None, platform_uuid=None, bluetooth_firmware=None, modem_firmware=None,
              bluetooth_transport=False, wlan_native_service=False):
    if checkpoint not in CHECKPOINTS:
        raise ValueError('Unsupported checkpoint in pinned XNU kernel')
    if userland_model not in (None, 'iPad7,11'):
        raise ValueError('Only the selected 20F66 iPad7,11 userland model is supported')
    cpus = []
    for i in range(8):
        props = {'device_type': STR('cpu'), 'state': STR('running' if i == 0 else 'waiting'),
                 'reg': U32(i << 8), 'cpu-id': U32(i),
                 'compatible': STR('arm,cortex-a55' if i < 4 else 'arm,cortex-a76'),
                 'timebase-frequency': U64(19200000), 'fixed-frequency': U64(19200000),
                 'clock-frequency': U64(1785600000 if i < 4 else 2419200000 if i < 7 else 2956800000)}
        if i < 4:
            props['small-core'] = U32(1)
        cpus.append(Node('cpu' + str(i), props))
    chosen = Node('chosen', {
        'random-seed': seed, 'nabu-handoff-version': U32(1),
        'crypto-hash-method': STR('sha2-384'),
        'mix-n-match-prevention-status': U32(1),
        'boot-manifest-hash': hashlib.sha384(b'nabu-20F66').digest(),
        'darwinboot-memory-size': U64(12 << 30), 'darwinboot-auto-memory': U32(1),
        'nabu-kernel-checkpoint': U32(checkpoint),
        'dram-base': U64(0), 'dram-size': U64(0),
        'debug-enabled': U32(1), 'psci-method': STR('smc'),
        'osenvironment': STR('main'), 'display-scale': U32(2),
        # Android HWC: 275.712 x 275.642 physical DPI; both K82 panel FDT
        # variants agree on 147.4 x 235.9 mm. This is not Android's 360 UI DPI.
        'nabu-panel-size-um': struct.pack('<2I', 147400, 235900),
        'display-rotation': U32(0), 'nvram-bank-size': U32(8192),
        'nvram-bank-count': U32(1), 'nvram-current-bank': U32(0),
        'nvram-proxy-data': nvram(),
    }, [Node('manifest-properties', {'BNCH': hashlib.sha384(b'nabu-20F66').digest()}),
        Node('memory-map', {'RAMDisk': bytes(16)} if bootstrap else None)])
    if rtc_offset is not None:
        chosen.props['nabu-rtc-offset'] = U64(rtc_offset)
    if platform_uuid is not None:
        chosen.props['nabu-platform-uuid'] = STR(str(uuid.UUID(platform_uuid)))
        chosen.props['nabu-usb-serial'] = STR(usb_serial_from_platform_uuid(platform_uuid))
    if wifi_mac is not None:
        # MobileGestalt reads this CFData before falling back to network-service
        # matching. This supplies board identity; it does not publish a NIC.
        chosen.props['mac-address-wifi0'] = validate_wifi_mac(wifi_mac)
    if image4_nonce_key is not None:
        if len(image4_nonce_key) != 16:
            raise ValueError('Image4 software nonce key must be 16 bytes')
        chosen.props['nabu-image4-nonce-key'] = image4_nonce_key
    tree = Node('device-tree', {
        # hw.product feeds MobileGestalt's device-class selection. Keep board
        # routing and the displayed hardware name separate from this opt-in
        # compatibility model for the supplied iPadOS userland.
        'model': STR(userland_model or 'Xiaomi Pad 5'), 'compatible': STR('xiaomi,nabu'),
        # Android reports this board as 21051182C. 20F66 ModelNumber reads
        # model-number from IODeviceTree:/; this is the Xiaomi model label.
        'model-number': STR('21051182C'),
        'platform-name': STR('nabu'), '#address-cells': U32(2), '#size-cells': U32(2),
    }, [chosen, Node('cpus', children=cpus),
        Node('arm-io', {'device_type': STR('qcom,sm8150'), '#address-cells': U32(2),
                       '#size-cells': U32(2), 'ranges': struct.pack('<3Q', 0, 0x17000000, 0x08000000)},
             [Node('gic', {'device_type': STR('interrupt-controller'), 'compatible': STR('arm,gic-v3'),
                           'reg': struct.pack('<4Q', 0xa00000, 0x10000, 0xa60000, 0x100000),
                           'virtual-timer-intid': U32(19)})]),
        Node('psci', {'compatible': STR('arm,psci-1.0'), 'method': STR('smc')}),
        # This is boot configuration, not hardware. IODTFindMatchingEntries
        # skips AAPL,ignore when publishing device nubs, while DT readers retain
        # these defaults. Publishing it left IOService busy and blocked configd.
        Node('defaults', {'AAPL,ignore': U32(1), 'sleep-disabled': U32(1), 'kern.vm_compressor': U32(2)}),
        Node('options'), Node('product', {'product-name': STR('Xiaomi Pad 5'),
                                        # About reads ArtworkTraits' product description;
                                        # CoreUI uses the tablet resource idiom.
                                        'product-description': STR('Xiaomi Pad 5'),
                                        'artwork-device-idiom': STR('pad'),
                                        'artwork-scale-factor': U32(2)})])
    if userland_model == 'iPad7,11':
        # Original 20F66 j171ap /product/product-id: MG requires 20 binary
        # bytes for its software platform table, independently of root model.
        # This selects donor software behavior, including Broadcom BT paths;
        # it does not describe or initialize the Nabu Qualcomm controller.
        product = next(n for n in tree.children if n.props['name'] == STR('product'))
        product.props['product-id'] = bytes.fromhex('4d013e8fae976e61a7b3b69cdb5a015fa7ff04bb')
    if userland_serial is not None:
        # IOPlatformExpertDevice publishes this NUL-terminated ADT data as
        # IOPlatformSerialNumber. Keep the value local and explicit.
        # The normal publication uses the first C string. If its allocation
        # fails, the inherited IODT fallback reads legacy offsets 13..20;
        # keep that read within this property without changing the C string.
        tree.props['serial-number'] = STR(validate_userland_serial(userland_serial)).ljust(32, b'\0')
    if touch_firmware is not None:
        tree.children.append(Node('nabu-touch', touch_firmware))
    if bluetooth_firmware is not None:
        tree.children.append(Node('nabu-bluetooth', {'compatible': STR('qcom,wcn3991-bt'), **bluetooth_firmware}))
        if bluetooth_transport:
            # 20F66 MG reads classic capability from the nonzero chosen MAC and
            # LE capability from the presence of /product/bluetooth-le.
            # address-hci is controller byte order; the DT identity is display order.
            chosen.props['mac-address-bluetooth0'] = bluetooth_firmware['address-hci'][::-1]
            product = next(n for n in tree.children if n.props['name'] == STR('product'))
            product.props['bluetooth-le'] = U32(1)
    if modem_firmware is not None:
        tree.children.append(Node('nabu-modem', {'compatible': STR('qcom,sm8150-mpss'), **modem_firmware}))
    if wlan_native_service:
        tree.children.append(Node('wlan', {
            'compatible': STR('qcom,wcn3990-wifi'),
            'device_type': STR('network'),
            'reg': struct.pack('<2Q', 0x18800000, 0x800000),
            'local-mac-address': validate_wifi_mac(wifi_mac),
        }))
    return tree


def parse(data):
    """Independent bounded decoder used to check the produced blob."""
    def node(offset, depth):
        if depth > 32 or offset + 8 > len(data):
            raise ValueError('Invalid ADT node')
        count, children = struct.unpack_from('<2I', data, offset)
        offset += 8
        props = {}
        for _ in range(count):
            if offset + 36 > len(data):
                raise ValueError('Truncated property header')
            name = data[offset:offset + 32]
            if b'\0' not in name:
                raise ValueError('Unterminated property name')
            name = name.split(b'\0', 1)[0].decode('ascii')
            length, = struct.unpack_from('<I', data, offset + 32)
            offset += 36
            if name in props or offset + length > len(data):
                raise ValueError('Duplicate/truncated property')
            props[name] = data[offset:offset + length]
            offset += (length + 3) & -4
        items = []
        for _ in range(children):
            child, offset = node(offset, depth + 1)
            items.append(child)
        return (props, items), offset
    tree, offset = node(0, 0)
    if offset != len(data):
        raise ValueError('ADT trailing bytes')
    return tree


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--checkpoint', type=int, choices=CHECKPOINTS, default=DEFAULT_CHECKPOINT)
    parser.add_argument('--bootstrap', action='store_true')
    parser.add_argument('--wifi-mac-file', type=Path,
                        help='Local file containing the six binary octets read from this device')
    parser.add_argument('--userland-model', choices=['iPad7,11'],
                        help='Use the supplied iPadOS model for hw.product/device-class compatibility')
    parser.add_argument('--userland-serial-file', type=Path,
                        help='Local ASCII compatibility serial; never read automatically from Android')
    args = parser.parse_args()
    wifi_mac = validate_wifi_mac(args.wifi_mac_file.read_bytes()) if args.wifi_mac_file else None
    userland_serial = (validate_userland_serial(args.userland_serial_file.read_text(encoding='ascii').strip())
                       if args.userland_serial_file else None)
    blob = make_tree(secrets.token_bytes(64), args.checkpoint, args.bootstrap, wifi_mac,
                     args.userland_model, userland_serial).encode()
    root, children = parse(blob)
    nodes = {p['name'].rstrip(b'\0').decode(): (p, c) for p, c in children}
    assert len(nodes['cpus'][1]) == 8
    assert [struct.unpack('<I', p['reg'])[0] for p, _ in nodes['cpus'][1]] == list(range(0, 0x800, 0x100))
    assert nodes['chosen'][0]['psci-method'] == b'smc\0'
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(blob)
    report = {'bytes': len(blob), 'sha256': hashlib.sha256(blob).hexdigest(), 'cpu_count': 8,
              'checkpoint': args.checkpoint,
              'bootstrap_ramdisk_required': args.bootstrap,
              'wifi_mac_supplied': wifi_mac is not None,
              'userland_model': args.userland_model,
              'compatibility_serial_supplied': userland_serial is not None,
              'window': 'largest successfully allocated EFI conventional run, capped at 12 GiB',
              'runtime_requirements': 'Nabu DarwinBoot handoff patch; boot MPIDR 0; CNTFRQ 19200000',
              'device_boot_validated': False, 'root_storage_driver_integrated': False}
    args.output.with_suffix(args.output.suffix + '.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
