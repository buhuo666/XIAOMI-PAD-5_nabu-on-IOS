"""Exercise 7-Zip against a synthetic FAT32 image; no target files or devices."""
import json
from pathlib import Path
import struct
import tempfile
from inspect_esp_image import inspect, CHAIN_FILES, ROOT
from make_nabu_adt import make_tree


def write_fat(path, files):
    # Small synthetic 128MiB FAT32 volume, with genuine VFAT long filenames.
    sector, total, reserved, fat_sectors = 512, 262144, 32, 2048
    root = {'children':{},'cluster':2,'parent':2}
    objects = [root]
    for name, data in files.items():
        node = root
        for part in Path(name).parts[:-1]:
            if part not in node['children']:
                node['children'][part] = {'children':{},'parent_node':node}
                objects.append(node['children'][part])
            node = node['children'][part]
        node['children'][Path(name).name] = {'data':data,'parent_node':node}
        objects.append(node['children'][Path(name).name])
    next_cluster = 2
    for obj in objects:
        obj['cluster'] = next_cluster
        obj['count'] = max(1,(len(obj.get('data',b''))+511)//512)
        next_cluster += obj['count']
    def entries(name, obj, index):
        short = (f'F{index:07d}'+'BIN').encode()
        checksum = 0
        for byte in short:
            checksum = (((checksum&1)<<7)+(checksum>>1)+byte)&255
        units = list(struct.unpack('<%dH'%len(name), name.encode('utf-16le')))+[0]
        units += [65535]*((-len(units))%13)
        output = bytearray()
        slots = [1,3,5,7,9,14,16,18,20,22,24,28,30]
        for i in reversed(range(len(units)//13)):
            entry = bytearray(32)
            entry[0]=(i+1)|(0x40 if i==len(units)//13-1 else 0)
            entry[11]=15; entry[13]=checksum
            for off,val in zip(slots,units[i*13:(i+1)*13]):
                struct.pack_into('<H',entry,off,val)
            output += entry
        entry=bytearray(32);entry[:11]=short;entry[11]=16 if 'children' in obj else 32
        struct.pack_into('<H',entry,20,obj['cluster']>>16)
        struct.pack_into('<H',entry,26,obj['cluster']&65535)
        struct.pack_into('<I',entry,28,len(obj.get('data',b'')))
        return output+entry
    for obj in objects:
        if 'children' in obj:
            obj['data']=b''.join(entries(name,child,i+1) for i,(name,child) in enumerate(obj['children'].items()))
            assert len(obj['data'])<512
    boot=bytearray(512);boot[:3]=b'\xeb\x58\x90';boot[3:11]=b'MSDOS5.0'
    struct.pack_into('<HBHB',boot,11,512,1,reserved,2)
    boot[21]=248;struct.pack_into('<HH',boot,24,63,255)
    struct.pack_into('<II',boot,32,total,fat_sectors)
    struct.pack_into('<IHH',boot,44,2,1,6)
    boot[64]=128;boot[66]=41;boot[71:82]=b'OFFLINETEST';boot[82:90]=b'FAT32   ';boot[510:]=b'\x55\xaa'
    info=bytearray(512)
    for off,val in [(0,0x41615252),(484,0x61417272),(488,0xffffffff),(492,0xffffffff),(508,0xaa550000)]:
        struct.pack_into('<I',info,off,val)
    fat=bytearray(fat_sectors*512);struct.pack_into('<II',fat,0,0x0ffffff8,0x0fffffff)
    for obj in objects:
        for c in range(obj['cluster'],obj['cluster']+obj['count']):
            struct.pack_into('<I',fat,c*4,c+1 if c+1<obj['cluster']+obj['count'] else 0x0fffffff)
    with path.open('wb') as output:
        output.truncate(total*sector)
        for offset,data in [(0,boot),(512,info),(6*512,boot),(7*512,info),
                            (reserved*512,fat),((reserved+fat_sectors)*512,fat)]:
            output.seek(offset);output.write(data)
        for obj in objects:
            output.seek((reserved+2*fat_sectors+obj['cluster']-2)*512)
            output.write(obj['data'])


def main():
    with tempfile.TemporaryDirectory(prefix='nabu-fat-fixture-') as temp:
        work=Path(temp);chain=work/'chain'
        files={name:b'synthetic-'+name.encode() for name in CHAIN_FILES}
        files[CHAIN_FILES[3]]=make_tree(bytes(range(64)),checkpoint=1,bootstrap=True).encode()
        files[CHAIN_FILES[5]]=b'[[entry]]\nid="nabu8796"\npath="kernel"\n'
        for relative,data in files.items():
            path=chain/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
        files['EFI/Nabu16/handoff-abc.txt']=b'kernel_checkpoint=1 callback_pa=180004000\n'
        image=work/'synthetic-fat.img';write_fat(image,files)
        report=inspect(image,chain,ROOT/'host/7zip/7z.exe',4*1024**3)
        assert all(f.get('bytes_equal') for f in report['files']),report
        assert report['actual_image_adt']['nabu_handoff_inputs_valid']
        assert report['handoff_records'][0]['fields']['kernel_checkpoint']==1
        assert report['geometry']['dump_covers_fat_volume']
        # Represent the reported divergence: ESP bytes changed after candidate inspection.
        changed=make_tree(bytes(range(64)),checkpoint=1,bootstrap=True)
        chosen=next(n for n in changed.children if n.props['name']==b'chosen\0')
        chosen.props['dram-base']=struct.pack('<Q',0xc0000000)
        chosen.props['dram-size']=struct.pack('<Q',0x140000000)
        files[CHAIN_FILES[3]]=changed.encode();del files['EFI/Nabu16/handoff-abc.txt']
        write_fat(image,files)
        report=inspect(image,chain,ROOT/'host/7zip/7z.exe')
        assert not report['files'][3]['bytes_equal']
        assert not report['actual_image_adt']['nabu_handoff_inputs_valid']
        assert not report['handoff_records']
    result={'passed':True,'cases':2,'method':'Actual bundled 7-Zip reads synthetic FAT32/VFAT image',
            'checks':['six files compare equal','long filenames preserved','handoff parsed',
                      'FAT volume distinguished from partition size','actual-image ADT divergence detected',
                      'nonzero DRAM rejected','absent handoff retained as observation'],
            'device_operations_performed':False}
    (ROOT/'esp-image-check.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,indent=2))


if __name__=='__main__':
    main()
