"""Bind the recovered 20F66 controller ABI to the emitted USB device family."""
import json
from pathlib import Path
import struct

from native_prelink import backed_offset, exports

ABI_PATH = Path(__file__).resolve().parents[1] / 'patches/nabu-usb/IOUSBDeviceController20F66.json'
MODULE = 'com.apple.iokit.IOUSBDeviceFamily'


def controller_symbols(kernel, image, report, methods):
    abi = json.loads(ABI_PATH.read_text())
    assert len(methods) == abi['slot_count'] == 232, 'Controller vtable layout differs'
    native = {name: va for va, names in exports(kernel, image).items() for name in names}
    extents = [e for e in report['extents'] if e['module'] == MODULE]

    def relocated(original):
        address = int(original, 16) + report['slide']
        assert any(e['va'] <= address < e['va'] + e['size'] for e in extents), original
        return address

    table = relocated(abi['vtable_symbol_original_va'])
    offset = backed_offset(image['segments'], table + 16, len(methods) * 8, len(kernel))
    pointers = struct.unpack_from('<232Q', kernel, offset)
    bindings = {}
    for method, pointer, slot in zip(methods, pointers, abi['slots']):
        if method in native:
            expected = native[method]
        else:
            expected = relocated(slot['original_va'])
            # Alias declarations encode only the slots. Unrecovered signatures
            # are never called by the adapter; the stock pointer is inherited.
            if slot.get('alias'):
                assert slot['alias'] in method, (slot['slot'], method)
        assert pointer == expected, (slot['slot'], method, hex(pointer), hex(expected))
        bindings[method] = pointer
    bindings.update(native)
    bindings['__ZTV21IOUSBDeviceController'] = table
    for name, field in [('constructor', 'constructor_original_va'),
                        ('destructor', 'destructor_original_va'),
                        ('metaclass', 'metaclass_original_va')]:
        bindings[abi[name + '_symbol']] = relocated(abi[field])
    for name, entry in abi['helper_bindings'].items():
        bindings['_' + name] = relocated(entry['original_va'])
    return bindings, {'module': MODULE, 'method_count': len(methods),
                      'vtable': table, 'class_bytes': abi['sizeof'],
                      'abi_source': str(ABI_PATH), 'runtime_verified': False}
