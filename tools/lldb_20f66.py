"""Executed inside Xcode LLDB's Python interpreter; creates no target process."""
import hashlib
import json
import os
from pathlib import Path

import lldb


def __lldb_init_module(debugger, internal_dict):
    plan = json.loads(Path(os.environ['NABU_NATIVE_ANALYSIS_PLAN']).read_text())
    output = {'scope': plan['scope'], 'targets': [], 'summary': [], 'all_ranges_decoded': True}
    for request in plan['targets']:
        target = debugger.CreateTargetWithFileAndArch(request['path'], 'arm64')
        if not target.IsValid():
            raise RuntimeError('Cannot create static LLDB target: ' + request['label'])
        result = {'label': request['label'], 'sha256': request['sha256'],
                  'lldb_triple': target.GetTriple(), 'module_uuid': target.GetModuleAtIndex(0).GetUUIDString(),
                  'symbols': []}
        for item in request['symbols']:
            symbol = dict(item)
            if item['status'] == 'code-range':
                address = int(item['address'], 16)
                decoded = target.ReadInstructions(target.ResolveFileAddress(address), item['bytes'] // 4)
                rows, raw = [], bytearray()
                for instruction in decoded:
                    location = instruction.GetAddress().GetFileAddress()
                    instruction_data = instruction.GetData(target)
                    error = lldb.SBError()
                    word = bytes(instruction_data.GetUnsignedInt8(error, i)
                                 for i in range(instruction.GetByteSize()))
                    if error.Fail():
                        raise RuntimeError(error.GetCString())
                    raw.extend(word)
                    rows.append({'address': hex(location), 'bytes': word.hex(),
                                 'mnemonic': instruction.GetMnemonic(target),
                                 'operands': instruction.GetOperands(target),
                                 'comment': instruction.GetComment(target)})
                complete = (len(rows) == item['bytes'] // 4 and
                            all(int(row['address'], 16) == address + i * 4 and len(row['bytes']) == 8
                                for i, row in enumerate(rows)) and
                            hashlib.sha256(raw).hexdigest() == item['sha256'])
                symbol.update(decoded_completely=complete, instructions=rows)
                output['all_ranges_decoded'] &= complete
            result['symbols'].append(symbol)
        output['targets'].append(result)
        output['summary'].append({'label': request['label'],
            'code_ranges': sum(s['status'] == 'code-range' for s in result['symbols']),
            'instructions': sum(len(s.get('instructions', [])) for s in result['symbols'])})
        debugger.DeleteTarget(target)
    Path(os.environ['NABU_NATIVE_ANALYSIS_OUTPUT']).write_text(json.dumps(output, indent=2) + '\n')
