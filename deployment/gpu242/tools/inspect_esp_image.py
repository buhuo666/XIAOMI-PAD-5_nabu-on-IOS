"""Compare a saved raw FAT32 ESP image with a local candidate. No device access."""
import argparse
import json
from pathlib import Path
import re
import struct
import subprocess
import tomllib
from inspect_early_boot import inspect_adt, inspect_handoff

ROOT = Path(__file__).resolve().parents[1]
CHAIN_FILES = ('EFI/Nabu16/UniXNU.efi', 'EFI/Nabu16/DarwinBoot.efi',
    'EFI/Nabu16/Payloads/kernel.macho', 'EFI/Nabu16/Payloads/kernel.macho.adt',
    'EFI/Nabu16/Payloads/bootstrap.apfs', 'EFI/UniXNU/unixnu.toml')


def run7z(exe, arguments):
    result = subprocess.run([str(exe), *map(str, arguments)], capture_output=True)
    if result.returncode:
        raise ValueError('7-Zip failed: ' + result.stderr.decode('utf-8', errors='replace'))
    return result.stdout


def inspect(image, chain, sevenzip, partition_bytes=None):
    # This entry accepts a raw partition image, not Android sparse or whole-disk images.
    with image.open('rb') as source:
        boot = source.read(512)
    if len(boot)!=512 or boot[510:512]!=b'\x55\xaa' or boot[82:90]!=b'FAT32   ':
        raise ValueError('Expected a raw FAT32 partition image (not Android sparse / whole disk).')
    sector = struct.unpack_from('<H', boot, 11)[0]
    sectors = struct.unpack_from('<H', boot, 19)[0] or struct.unpack_from('<I', boot, 32)[0]
    volume_bytes = sector*sectors
    geometry = {'dump_bytes':image.stat().st_size, 'fat_volume_bytes':volume_bytes,
                'bytes_per_sector':sector, 'reported_partition_bytes':partition_bytes,
                'dump_covers_fat_volume':image.stat().st_size>=volume_bytes}
    listing = run7z(sevenzip, ['l', '-slt', '-sccUTF-8', image]).decode('utf-8')
    records = []
    for section in re.split(r'\r?\n\r?\n', listing):
        fields = dict(line.split(' = ',1) for line in section.splitlines() if ' = ' in line)
        if fields.get('Path') and 'Size' in fields and fields.get('Folder')!='+':
            records.append(fields['Path'].replace('\\','/'))
    def read(member):
        return run7z(sevenzip, ['x', '-so', '-y', image, member])
    results, contents = [], {}
    for relative in CHAIN_FILES:
        matches = [n for n in records if n.casefold()==relative.casefold()]
        entry = {'path':relative, 'image_matches':len(matches)}
        if len(matches)==1:
            data = read(matches[0])
            contents[relative] = data
            candidate = chain/relative
            entry.update(image_bytes=len(data), candidate_exists=candidate.is_file())
            if candidate.is_file():
                expected = candidate.read_bytes()
                entry.update(candidate_bytes=len(expected), bytes_equal=data==expected)
        results.append(entry)
    adt = contents.get(CHAIN_FILES[3])
    try:
        adt_report = inspect_adt(adt) if adt else {'error':'ADT missing or ambiguous'}
    except (ValueError, StopIteration, struct.error) as error:
        adt_report = {'error':'Cannot decode expected chosen node: '+str(error)}
    handoffs = []
    for name in records:
        if re.fullmatch(r'EFI/Nabu16/handoff-[0-9a-fA-F]+\.txt', name, flags=re.I):
            handoffs.append({'path':name, 'fields':inspect_handoff(read(name).decode('utf-8'))})
    findings = []
    if not geometry['dump_covers_fat_volume']:
        findings.append('Dump is shorter than the FAT volume: missing files cannot be ruled out.')
    if partition_bytes and image.stat().st_size<partition_bytes:
        findings.append('This is not a complete partition dump. A smaller FAT volume may still fit; compare BPB volume size.')
    if not all(f.get('bytes_equal') is True for f in results):
        findings.append('Saved ESP image does not contain all six exact candidate files.')
    if not adt_report.get('nabu_handoff_inputs_valid'):
        findings.append('ADT read from the saved ESP image does not satisfy the nabu callback contract.')
    if not handoffs:
        findings.append('No handoff record found in the readable FAT filesystem; does not prove checkpoint 1 was not reached.')
    menu = {}
    if CHAIN_FILES[5] in contents:
        config = tomllib.loads(contents[CHAIN_FILES[5]].decode('utf-8'))
        menu = {'entries':[{'id':e.get('id'),'path':e.get('path'),'initrd':e.get('initrd')}
                           for e in config.get('entry',[])],
                'drivers':[d.get('path') for d in config.get('driver',[])]}
    return {'geometry':geometry, 'files':results, 'actual_image_adt':adt_report,
            'actual_image_menu':menu, 'handoff_records':handoffs, 'findings':findings,
            'device_operations_performed':False,
            'limits':['Saved-image inspection does not prove the tablet loaded this volume.',
                      'The dump must have been taken after this boot; erased/reflashed images lose earlier evidence.']}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--image',type=Path,required=True)
    p.add_argument('--chain',type=Path,required=True)
    p.add_argument('--partition-bytes',type=int,help='Actual nabu_esp blockdev size, if known')
    p.add_argument('--7zip',dest='sevenzip',type=Path,default=ROOT/'host/7zip/7z.exe')
    p.add_argument('--output',type=Path,required=True)
    a = p.parse_args()
    report = inspect(a.image,a.chain,a.sevenzip,a.partition_bytes)
    a.output.parent.mkdir(parents=True,exist_ok=True)
    with a.output.open('x',encoding='utf-8') as output:
        json.dump(report,output,ensure_ascii=False,indent=2)
        output.write('\n')
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
