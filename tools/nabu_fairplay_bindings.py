"""Preserve the supplied 20F66 FairPlayIOKit's encoded kernel import addends.

These are exact original addresses, not a nearest-symbol resolver. The original
code decodes its pointer-table entries before use; rebinding must retain the
addend as well as the named export. Evidence: native-usb-v54/fairplay-kext-analysis.
"""
import json
from pathlib import Path
import emit_prelink
import native_prelink
from emit_prelink import emit


ENCODED_IMPORTS = {
    0xfffffff0071e25d7: ('_ipc_port_release_send', 3),
    0xfffffff00732e086: ('_random', 2),
    0xfffffff00776c9e3: ('_IOFreeData', 3),
    0xfffffff00776c2a6: ('_IOMallocTypeImpl', 2),
    0xfffffff0071fd69a: ('_host_priv_self', 2),
    0xfffffff00776c93b: ('_IOMallocData', 3),
    0xfffffff00776ca47: ('_IOFreeTypeVarImpl', 3),
    0xfffffff00776cbfb: ('_IOLog', 3),
    0xfffffff00776bd02: ('_IOMallocAligned', 2),
    0xfffffff0071fd4b7: ('_host_get_special_port', 3),
    0xfffffff00776ca33: ('_IOMallocTypeVarImpl', 3),
    0xfffffff00776bd1a: ('_IOFreeAligned', 2),
    0xfffffff00776ca32: ('_IOMallocTypeVarImpl', 2),
    0xfffffff00776c46b: ('_IOFreeTypeImpl', 3),
    0xfffffff007195be6: ('_kernel_map', 6),
    0xfffffff00776bd1b: ('_IOFreeAligned', 3),
    0xfffffff0071048aa: ('_ipc_kernel_map', 2),
    0xfffffff00776c46a: ('_IOFreeTypeImpl', 2),
    0xfffffff00776ca46: ('_IOFreeTypeVarImpl', 2),
    0xfffffff00712c133: ('_PAGE_SHIFT_CONST', 3),
    0xfffffff00776c93a: ('_IOMallocData', 2),
    0xfffffff00732e087: ('_random', 3),
    0xfffffff0071c8fe2: ('_strlen', 2),
}


def emit_with_fairplay(native, original, roots, slide):
    exact_binding = native_prelink.unique_kernel_binding
    decode_relative = emit_prelink.pc_relative_target
    padding_path = Path(__file__).resolve().parents[1] / 'patches/nabu-fairplay/20F66-opaque-words.json'
    padding = json.loads(padding_path.read_text())
    opaque_words = {int(pc, 16): int(word, 16) for pc, word in padding['words'].items()}
    observed = []
    retained_words = []

    def bind(address, original_exports, native_by_name):
        if address not in ENCODED_IMPORTS:
            return exact_binding(address, original_exports, native_by_name)
        name, addend = ENCODED_IMPORTS[address]
        assert name in original_exports.get(address - addend, []), (hex(address), name)
        choices = native_by_name.get(name, set())
        assert len(choices) == 1, (name, choices)
        replacement = next(iter(choices)) + addend
        observed.append({'original_target': hex(address), 'symbol': name,
                         'addend': addend, 'new_target': hex(replacement)})
        return replacement

    def relative_target(word, pc):
        if pc not in opaque_words:
            return decode_relative(word, pc)
        assert word == opaque_words[pc], hex(pc)
        retained_words.append(hex(pc))
        return None

    # The pinned emitter exposes its resolver at module scope. Scope this
    # binding to one build, leaving the ordinary APFS/USB path unchanged.
    native_prelink.unique_kernel_binding = bind
    emit_prelink.pc_relative_target = relative_target
    try:
        image, report = emit(native, original, roots, slide)
    finally:
        native_prelink.unique_kernel_binding = exact_binding
        emit_prelink.pc_relative_target = decode_relative
    report['fairplay_encoded_kernel_imports'] = observed
    report['fairplay_opaque_words'] = {'source': str(padding_path), 'retained': retained_words,
                                     'classification': padding['classification'],
                                     'limitations': padding['limitations']}
    return image, report
