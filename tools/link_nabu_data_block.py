#!/usr/bin/env python3
"""Link the Data block kext into the original-APFS prelink image."""
import argparse
from collections import OrderedDict
import json
from pathlib import Path
import struct
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src/XnuPrelink'))
from native_prelink import macho, backed_offset, exports, unserialize_xml
from emit_prelink import to_xml

COALESCED = {'__TEXT': '__PRELINK_TEXT', '__TEXT_EXEC': '__PLK_TEXT_EXEC',
             '__DATA_CONST': '__PLK_DATA_CONST', '__DATA': '__PRELINK_DATA'}
BUNDLE = 'org.nabu.driver.DataBlock'


def align(value, boundary=0x4000):
    return (value + boundary - 1) & -boundary


def signed(value, bits):
    return value - (1 << bits) if value & (1 << (bits - 1)) else value


class Object:
    def __init__(self, path):
        self.path = Path(path)
        self.data = self.path.read_bytes()
        self.image = macho(self.data)
        self.sections = []
        for segment in self.image['segments']:
            for source in segment['sections']:
                section = dict(source)
                at = section['command_offset']
                segment_name = self.data[at + 16:at + 32].rstrip(b'\0').decode()
                section['align'], ro, count, flags = struct.unpack_from('<4I', self.data, at + 52)
                section['flags'] = flags
                section['relocations'] = [struct.unpack_from('<II', self.data, ro + i * 8) for i in range(count)]
                section['ordinal'] = len(self.sections) + 1
                section['keep'] = segment_name != '__DWARF' and section['name'] not in ('__compact_unwind', '__eh_frame')
                if flags & 0x80000400 or section['name'] == '__text':
                    section['group'] = '__TEXT_EXEC'
                elif segment_name == '__TEXT':
                    section['group'] = '__TEXT'
                elif segment_name == '__DATA_CONST' or section['name'] in ('__const', '__mod_init_func', '__mod_term_func'):
                    section['group'] = '__DATA_CONST'
                else:
                    section['group'] = '__DATA'
                self.sections.append(section)
        at = next(at for cmd, at, _ in self.image['commands'] if cmd == 2)
        sy, count, st, _ = struct.unpack_from('<4I', self.data, at + 8)
        self.symbols = []
        for i in range(count):
            ix, kind, section, desc, value = struct.unpack_from('<IBBHQ', self.data, sy + i * 16)
            name = self.data[st + ix:self.data.index(b'\0', st + ix)].decode()
            self.symbols.append({'name': name, 'kind': kind, 'section': section, 'desc': desc, 'value': value})

    def symbol_address(self, symbol, definitions):
        kind = symbol['kind'] & 0xe
        if kind == 0xe:
            section = self.sections[symbol['section'] - 1]
            return section['new_va'] + symbol['value'] - section['va']
        if kind == 2:
            return symbol['value']
        return definitions[symbol['name']]


def reference_vtable(reference, class_name='IOBlockStorageDevice'):
    mangled = str(len(class_name)) + class_name
    symbol = next(s for s in reference.symbols if s['name'] == '__ZTV' + mangled)
    section = reference.sections[symbol['section'] - 1]
    names = {}
    for address, word in section['relocations']:
        if word >> 27 & 1 and word >> 28 == 0:
            names[section['va'] + address] = reference.symbols[word & 0xffffff]['name']
    methods = []
    address = symbol['value'] + 16
    while address in names:
        methods.append(names[address])
        address += 8
    return methods


def storage_symbols(kernel, image, report, reference, class_name="IOBlockStorageDevice", module="com.apple.iokit.IOStorageFamily"):
    """Use the newly compiled 16.5 class's slots to name the original methods."""
    native = {name: va for va, names in exports(kernel, image).items() for name in names}
    methods = reference_vtable(reference, class_name)
    mangled = str(len(class_name)) + class_name
    extents = [e for e in report['extents'] if e['module'] == module]
    const = next(e for e in extents if e['segment'] == '__DATA_CONST')
    text = next(e for e in extents if e['segment'] == '__TEXT_EXEC')

    def read(va, size):
        at = backed_offset(image['segments'], va, size, len(kernel))
        return kernel[at:at + size]

    inherited = [(i, native[name]) for i, name in enumerate(methods) if name in native]
    blob = read(const['va'], const['size'])
    candidates = []
    for at in range(0, len(blob) - (len(methods) + 2) * 8 + 1, 8):
        if blob[at:at + 16] == bytes(16) and all(struct.unpack_from('<Q', blob, at + 16 + i * 8)[0] == value for i, value in inherited):
            candidates.append(at)
    if class_name == 'IOAESAccelerator':
        # The original base and its queued implementation share inherited
        # slots. The base's algorithm getter returns its AES-CBC string.
        slot = methods.index('__ZN16IOAESAccelerator16getAlgorithmNameEv')
        selected = []
        for at in candidates:
            function = struct.unpack_from('<Q', blob, at + 16 + slot * 8)[0]
            page, add, ret = struct.unpack('<3I', read(function, 12))
            if page & 0x9f00001f != 0x90000000 or add & 0xffc003ff != 0x91000000 or ret != 0xd65f03c0:
                continue
            delta = signed(((page >> 5 & 0x7ffff) << 2) | (page >> 29 & 3), 21)
            name = (function & ~4095) + delta * 4096 + (add >> 10 & 4095)
            if read(name, 8) == b'AES-CBC\0':
                selected.append(at)
        candidates = selected
    if len(candidates) != 1:
        raise ValueError(f'{class_name} vtable match count: {len(candidates)}')
    table = const['va'] + candidates[0]
    pointers = struct.unpack('<' + 'Q' * len(methods), read(table + 16, len(methods) * 8))
    bindings = dict(zip(methods, pointers))
    bindings.update(native)
    bindings['__ZTV' + mangled] = table
    getter = next(p for name, p in zip(methods, pointers) if name == '__ZNK' + mangled + '12getMetaClassEv')
    adrp, add = struct.unpack('<II', read(getter, 8))
    immediate = signed(((adrp >> 5 & 0x7ffff) << 2) | (adrp >> 29 & 3), 21)
    bindings['__ZN' + mangled + '10gMetaClassE'] = (getter & ~4095) + immediate * 4096 + (add >> 10 & 4095)
    code = read(text['va'], text['size'])
    constructors = []
    for at in range(0, len(code) - 32, 4):
        words = struct.unpack_from('<8I', code, at)
        if (words[:2] == (0xa9bf7bfd, 0x910003fd) and words[2] & 0xfc000000 == 0x94000000 and
                words[3] & 0x9f00001f == 0x90000008 and words[4] & 0xffc003ff == 0x91000108 and
                words[5:] == (0xf9000008, 0xa8c17bfd, 0xd65f03c0)):
            pc = text['va'] + at
            imm = signed(((words[3] >> 5 & 0x7ffff) << 2) | (words[3] >> 29 & 3), 21)
            stored = ((pc + 12) & ~4095) + imm * 4096 + (words[4] >> 10 & 4095)
            if stored == table + 16:
                constructors.append(pc)
    if not constructors:
        raise ValueError(f'{class_name} constructor not found')
    destructor = pointers[0] - 4
    branch, = struct.unpack('<I', read(destructor, 4))
    if branch & 0xfc000000 != 0x14000000:
        raise ValueError('IOBlockStorageDevice base destructor requires native analysis')
    bindings['__ZN' + mangled + 'C2EPK11OSMetaClass'] = constructors[0]
    bindings['__ZN' + mangled + 'D2Ev'] = destructor
    return bindings, {'method_count': len(methods), 'vtable': table, 'constructor': constructors[0],
                      'base_destructor': destructor,
                      'metaclass': bindings['__ZN' + mangled + '10gMetaClassE']}


def relocate_object(obj, output, image, definitions, got, stubs):
    pointers = []
    counts = {}
    for section in obj.sections:
        if not section['keep'] or not section['size']:
            continue
        index = 0
        relocs = section['relocations']
        while index < len(relocs):
            address, word = relocs[index]
            index += 1
            kind, external, length = word >> 28, word >> 27 & 1, 1 << (word >> 25 & 3)
            symbol_index = word & 0xffffff
            addend = 0
            if kind == 10:  # ARM64_RELOC_ADDEND prefixes an instruction relocation.
                addend = signed(symbol_index, 24)
                address, word = relocs[index]
                index += 1
                kind, external, length = word >> 28, word >> 27 & 1, 1 << (word >> 25 & 3)
                symbol_index = word & 0xffffff
            site = section['new_va'] + address
            at = backed_offset(image['segments'], site, length, len(output))
            counts[str(kind)] = counts.get(str(kind), 0) + 1
            if external:
                symbol = obj.symbols[symbol_index]
                target = obj.symbol_address(symbol, definitions)
            else:
                target_section = obj.sections[symbol_index - 1]
                target = target_section['new_va'] - target_section['va']
            target += addend
            if kind == 0:  # ARM64_RELOC_UNSIGNED
                value = int.from_bytes(output[at:at + length], 'little') + target
                output[at:at + length] = (value % (1 << (length * 8))).to_bytes(length, 'little')
                if length == 8 and value >= 0xfffffff000000000:
                    pointers.append(site)
                continue
            if kind == 1:  # SUBTRACTOR is followed by UNSIGNED at the same site.
                _, unsigned_word = relocs[index]
                index += 1
                other = obj.symbols[unsigned_word & 0xffffff]
                value = int.from_bytes(output[at:at + length], 'little') + obj.symbol_address(other, definitions) - target
                output[at:at + length] = (value % (1 << (length * 8))).to_bytes(length, 'little')
                continue
            instruction = struct.unpack_from('<I', output, at)[0]
            if kind in (5, 6, 7):
                target = got[target - addend] + addend
            if kind == 2:  # BRANCH26
                delta = target + signed(instruction & 0x3ffffff, 26) * 4 - site
                if not -(1 << 27) <= delta < (1 << 27):
                    delta = stubs[target] - site
                instruction = instruction & 0xfc000000 | (delta >> 2 & 0x3ffffff)
            elif kind in (3, 5):  # PAGE21 or GOT_LOAD_PAGE21
                delta = (target & ~4095) - (site & ~4095)
                imm = delta >> 12
                instruction = instruction & 0x9f00001f | (imm & 3) << 29 | (imm >> 2 & 0x7ffff) << 5
            elif kind in (4, 6):  # PAGEOFF12 or GOT_LOAD_PAGEOFF12
                scale = 0
                if instruction & 0x3b000000 == 0x39000000:
                    scale = instruction >> 30
                    if instruction & 0x04800000 == 0x04800000:
                        scale = 4
                instruction = instruction & ~0x003ffc00 | ((target & 4095) >> scale) << 10
            elif kind == 7:  # POINTER_TO_GOT, signed PC-relative displacement.
                instruction = (target - site + signed(instruction, 32)) & 0xffffffff
            else:
                raise ValueError(f'Unsupported arm64 relocation {kind} in {obj.path.name}')
            struct.pack_into('<I', output, at, instruction)
    return pointers, counts


def link(kernel, report, reference, objects, aes_reference=None, usb_reference=None):
    output = bytearray(kernel)
    image = macho(output)
    by_segment = {s['name']: s for s in image['segments']}
    info = by_segment['__PRELINK_INFO']
    metadata = unserialize_xml(output[info['fileoff']:info['fileoff'] + info['filesize']])
    bindings, storage = storage_symbols(output, image, report, reference)
    usb = None
    if usb_reference:
        from nabu_native_usb_abi import controller_symbols
        usb_bindings, usb = controller_symbols(output, image, report,
            reference_vtable(usb_reference, 'IOUSBDeviceController'))
        bindings.update(usb_bindings)
    aes = None
    if aes_reference:
        aes_bindings, aes = storage_symbols(output, image, report, aes_reference, "IOAESAccelerator", "com.apple.iokit.IOCryptoAcceleratorFamily")
        bindings.update(aes_bindings)
    merged = OrderedDict()
    for obj in objects:
        for section in obj.sections:
            if not section['keep'] or not section['size']:
                continue
            key = (section['group'], section['name'])
            group = merged.setdefault(key, {'group': key[0], 'name': key[1], 'flags': section['flags'],
                                           'align': section['align'], 'size': 0, 'inputs': []})
            group['align'] = max(group['align'], section['align'])
            section['group_offset'] = align(group['size'], 1 << section['align'])
            group['size'] = section['group_offset'] + section['size']
            group['inputs'].append((obj, section))
    got_targets = set()
    branch_targets = set()
    # External GOT entries are reserved first; addresses are resolved after layout.
    for obj in objects:
        for section in obj.sections:
            if section['keep']:
                for _, word in section['relocations']:
                    if word >> 28 in (5, 6, 7):
                        got_targets.add((objects.index(obj), word & 0xffffff))
                    elif word >> 28 == 2 and word >> 27 & 1:
                        branch_targets.add((objects.index(obj), word & 0xffffff))
    got_targets.update(branch_targets)
    if got_targets:
        merged[('__DATA_CONST', '__got')] = {'group': '__DATA_CONST', 'name': '__got', 'flags': 0,
                                           'align': 3, 'size': 8 * len(got_targets), 'inputs': []}
    if branch_targets:
        merged[('__TEXT_EXEC', '__stubs')] = {'group': '__TEXT_EXEC', 'name': '__stubs', 'flags': 0x80000400,
                                            'align': 2, 'size': 12 * len(branch_targets), 'inputs': []}
    header_size = 32 + 4 * 72 + len(merged) * 80 + 16
    layouts = OrderedDict()
    for group, parent_name in COALESCED.items():
        parent = by_segment[parent_name]
        occupied = [e['va'] + e['size'] for e in report['extents']
                    if parent['va'] <= e['va'] < parent['va'] + parent['size']]
        if group == '__TEXT':
            occupied += [e['_PrelinkExecutableLoadAddr'] + e['_PrelinkExecutableSize']
                         for e in metadata['_PrelinkInfoDictionary'] if e.get('_PrelinkExecutableLoadAddr') and
                         parent['va'] <= e['_PrelinkExecutableLoadAddr'] < parent['va'] + parent['size']]
        base = align(max(occupied, default=parent['va']))
        cursor = base + align(header_size, 0x1000) if group == '__TEXT' else base
        for section in merged.values():
            if section['group'] != group:
                continue
            cursor = align(cursor, 1 << section['align'])
            section['va'] = cursor
            for _, part in section['inputs']:
                part['new_va'] = cursor + part['group_offset']
            cursor += section['size']
        size = align(cursor - base, 0x1000)
        limit = parent['va'] + parent['size']
        if group == '__TEXT':
            limit -= (len(report['sparse_index']['headers']) + 1) * 8
        if base + size > limit:
            raise ValueError(f'Insufficient prelink space for DataBlock {group}')
        layouts[group] = {'va': base, 'size': size, 'fileoff': parent['fileoff'] + base - parent['va'],
                          'prot': 5 if group == '__TEXT_EXEC' else 3 if group == '__DATA' else 1}
    definitions = dict(bindings)
    for obj in objects:
        for symbol in obj.symbols:
            if symbol['kind'] & 0xe0 or not symbol['kind'] & 0xe:
                continue
            if symbol['kind'] & 0xe == 0xe and not obj.sections[symbol['section'] - 1]['keep']:
                continue
            definitions[symbol['name']] = obj.symbol_address(symbol, definitions)
    for section in merged.values():
        for obj, part in section['inputs']:
            at = backed_offset(image['segments'], part['new_va'], part['size'], len(output))
            if part['flags'] & 0xff in (1, 0xc, 0x12):
                output[at:at + part['size']] = bytes(part['size'])
            else:
                output[at:at + part['size']] = obj.data[part['fileoff']:part['fileoff'] + part['size']]
    got, pointer_sites = {}, []
    for i, (oi, si) in enumerate(sorted(got_targets)):
        target = objects[oi].symbol_address(objects[oi].symbols[si], definitions)
        site = merged[('__DATA_CONST', '__got')]['va'] + i * 8
        got[target] = site
        at = backed_offset(image['segments'], site, 8, len(output))
        struct.pack_into('<Q', output, at, target)
        pointer_sites.append(site)
    relocation_counts = {}
    stubs = {}
    for i, (oi, si) in enumerate(sorted(branch_targets)):
        target = objects[oi].symbol_address(objects[oi].symbols[si], definitions)
        site = merged[('__TEXT_EXEC', '__stubs')]['va'] + i * 12
        slot = got[target]
        pages = ((slot & ~4095) - (site & ~4095)) >> 12
        words = (0x90000010 | (pages & 3) << 29 | (pages >> 2 & 0x7ffff) << 5,
                 0xf9400210 | ((slot & 4095) >> 3) << 10, 0xd61f0200)
        struct.pack_into('<3I', output, backed_offset(image['segments'], site, 12, len(output)), *words)
        stubs[target] = site
    for obj in objects:
        sites, counts = relocate_object(obj, output, image, definitions, got, stubs)
        pointer_sites.extend(sites)
        relocation_counts[obj.path.name] = counts
    commands = []
    for group, layout in layouts.items():
        sections = [s for s in merged.values() if s['group'] == group]
        command = bytearray(struct.pack('<II16s4Q4I', 0x19, 72 + 80 * len(sections), group.encode(),
            layout['va'], layout['size'], layout['fileoff'], layout['size'], layout['prot'], layout['prot'], len(sections), 0))
        for section in sections:
            fileoff = backed_offset(image['segments'], section['va'], section['size'], len(output))
            # Zerofill has already been materialized in the parent image.
            flags = section['flags']
            if flags & 0xff in (1, 0xc, 0x12):
                flags &= ~0xff
            command.extend(struct.pack('<16s16sQQ8I', section['name'].encode(), group.encode(), section['va'],
                section['size'], fileoff, section['align'], 0, 0, flags, 0, 0, 0))
        commands.append(command)
    # Relocations are already applied. The command marks this as a split kext
    # for XNU's coalesced-segment metadata and allocation walkers.
    commands.append(struct.pack('<4I', 0x1e, 16, 0, 0))
    header = struct.pack('<8I', 0xfeedfacf, 0x100000c, 0, 0xb, len(commands), sum(map(len, commands)), 0x21, 0) + b''.join(commands)
    text_layout = layouts['__TEXT']
    output[text_layout['fileoff']:text_layout['fileoff'] + len(header)] = header
    kmod = definitions['_kmod_info']
    metadata['_PrelinkInfoDictionary'].append({
        'CFBundleIdentifier': BUNDLE, 'CFBundleName': 'Nabu Data Block', 'CFBundleExecutable': 'NabuDataBlock',
        'CFBundlePackageType': 'KEXT', 'CFBundleVersion': '1.0', 'OSBundleCompatibleVersion': '1.0',
        'OSBundleRequired': 'Local-Root', '_PrelinkBundlePath': '/System/Library/Extensions/NabuDataBlock.kext',
        '_PrelinkExecutableRelativePath': 'NabuDataBlock', '_PrelinkExecutableLoadAddr': text_layout['va'],
        '_PrelinkExecutableSourceAddr': text_layout['va'], '_PrelinkExecutableSize': text_layout['size'],
        '_PrelinkKmodInfo': kmod, 'OSBundleLibraries': {'com.apple.iokit.IOStorageFamily': '2.1',
            'com.apple.kpi.iokit': '8.0', 'com.apple.kpi.libkern': '8.0', 'com.apple.kpi.mach': '8.0',
            'com.apple.kpi.bsd': '8.0', 'com.apple.kpi.private': '8.0', 'com.apple.iokit.IOCryptoAcceleratorFamily': '1.0'}})
    if usb:
        metadata['_PrelinkInfoDictionary'][-1]['OSBundleLibraries']['com.apple.iokit.IOUSBDeviceFamily'] = '2.0'
    prelink = by_segment['__PRELINK_TEXT']
    old_offsets = struct.unpack('<' + 'I' * (len(metadata['_PrelinkLinkKASLROffsets']) // 4), metadata['_PrelinkLinkKASLROffsets'])[1:]
    offsets = sorted(set(old_offsets) | {site - prelink['va'] for site in pointer_sites})
    metadata['_PrelinkLinkKASLROffsets'] = struct.pack('<' + 'I' * (len(offsets) + 1), len(offsets), *offsets)
    headers = sorted([*report['sparse_index']['headers'], text_layout['va']])
    index_size = len(headers) * 8
    index_va = prelink['va'] + prelink['size'] - index_size
    index_at = backed_offset(image['segments'], index_va, index_size, len(output))
    struct.pack_into('<' + 'Q' * len(headers), output, index_at, *headers)
    section = next(s for s in prelink['sections'] if s['name'] == '__macho_list')
    struct.pack_into('<QQI', output, section['command_offset'] + 32, index_va, index_size, index_at)
    struct.pack_into('<Q', output, prelink['sections'][0]['command_offset'] + 40, index_va - prelink['va'])
    xml = ET.tostring(to_xml(metadata), encoding='utf-8').replace(b' />', b'/>') + b'\0'
    info_size = align(len(xml))
    info_at = align(len(output))
    output.extend(bytes(info_at - len(output)) + xml + bytes(info_size - len(xml)))
    struct.pack_into('<4Q', output, info['command_offset'] + 24, info['va'], info_size, info_at, info_size)
    struct.pack_into('<QQI', output, info['sections'][0]['command_offset'] + 32, info['va'], info_size, info_at)
    detail = {'bundle': BUNDLE, 'storage_class': storage, 'aes_class': aes, 'usb_class': usb, 'segments': layouts, 'kmod_info': kmod,
              'start': definitions.get('_nabu_data_block_start'),
              'wireless_start': definitions.get('_nabu_wireless_start'),
              'bluetooth_trial': definitions.get('_nabu_bluetooth_version_trial'), 'relocations': relocation_counts,
              'pointer_sites_added': len(pointer_sites), 'sparse_headers': headers,
              'sparse_index': {'va': index_va, 'size': index_size, 'fileoff': index_at, 'headers': headers, 'abi': 1},
              'imports': {s['name']: definitions[s['name']] for obj in objects for s in obj.symbols
                          if s['kind'] == 1}, 'runtime_tested': False}
    return bytes(output), detail


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kernel', type=Path, required=True)
    parser.add_argument('--prelink-report', type=Path)
    parser.add_argument('--reference-object', type=Path, required=True)
    parser.add_argument('--aes-reference-object', type=Path)
    parser.add_argument('--usb-reference-object', type=Path)
    parser.add_argument('--object', type=Path, action='append', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report_path = args.prelink_report or args.kernel.with_name('prelink-report.json')
    prelink_report = json.loads(report_path.read_text())
    result, report = link(args.kernel.read_bytes(), prelink_report,
                          Object(args.reference_object), [Object(p) for p in args.object],
                          Object(args.aes_reference_object) if args.aes_reference_object else None,
                          Object(args.usb_reference_object) if args.usb_reference_object else None)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / 'kernel.native-apfs.macho').write_bytes(result)
    (args.output / 'data-block-link.json').write_text(json.dumps(report, indent=2) + '\n')
    prelink_report.pop('candidate_sha256', None)
    prelink_report.update(candidate_bytes=len(result), data_block=report,
                          sparse_index=report['sparse_index'], runtime_qualified=False)
    prelink_report['components'].append(BUNDLE)
    prelink_report['extents'].extend({'module': BUNDLE, 'segment': name, 'va': segment['va'],
                                     'size': segment['size']} for name, segment in report['segments'].items())
    (args.output / 'prelink-report.json').write_text(json.dumps(prelink_report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
