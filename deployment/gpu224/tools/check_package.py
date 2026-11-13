"""Offline checks only. Does not enumerate or communicate with any device."""
import ast
import hashlib
import importlib
import json
from pathlib import Path
import plistlib
import struct
import subprocess
import sys
import tempfile
import tomllib
from scan_target import make_plan
from import_system import select_components, validate_raw
ROOT=Path(__file__).resolve().parents[1]

def main():
    passed=[]
    def check(value,name):
        if not value: raise AssertionError(name)
        passed.append(name)
    for path in (ROOT/'tools').glob('*.py'):
        ast.parse(path.read_text(encoding='utf-8'),filename=str(path))
    passed.append('all package Python files parse')
    for name in ['stage_nabu_boot_chain','run_nabu_temporary_boot','nabu_runtime_logs',
                 'install_ipados_windows','make_nabu_adt','prepare_chain','prepare_target_identity']:
        importlib.import_module(name)
    passed.append('deployment dependency imports')
    for capacity in (128,256):
        end=capacity*1024**3//4096-257
        userdata={'number':34,'name':'userdata','first_lba':8*1024**3//4096,'last_lba':end,
                  'bytes':(end+1-8*1024**3//4096)*4096}
        unit={'name':'sda','logical_block_bytes':4096,'bytes':capacity*1024**3,'partitions':[userdata]}
        plan=make_plan({'luns':[unit]})
        check(plan['status']=='offline-repartition-required',f'{capacity} GiB is a plan, not an applied layout')
        esp,system=plan['partitions_proposed']
        check(esp['bytes']==4*1024**3 and system['bytes']==60*1024**3 and
              esp['last_lba']+1==system['first_lba'] and system['last_lba']<=end and
              plan['userdata_last_lba_proposed']+1==esp['first_lba'],f'{capacity} GiB non-overlapping bounded geometry')
        check(plan['android_data_preserved'] is False,f'{capacity} GiB does not promise lossless shrinking')
        unit['partitions'].extend([esp,system])
        userdata['last_lba']=esp['first_lba']-1
        check(make_plan({'luns':[unit]})['status']=='existing-layout-candidate',f'{capacity} GiB detects prepared layout')
        system['bytes']-=4096
        check(make_plan({'luns':[unit]})['status']=='existing-layout-needs-port',f'{capacity} GiB rejects wrong partition size')
    from nabu_storage_layout import geometry, select_layout
    template=json.loads((ROOT/'configs/nabu-storage-layout.json').read_text())
    # Synthetic GPT fixtures exercise selected capacity only. They never
    # describe a connected tablet or authorize partition changes.
    for total in (32,64,128,256,512,33):
        storage=geometry(select_layout(template,total))
        disk_bytes=(total+32)*1024**3
        end=disk_bytes//4096-257
        userdata={'number':34,'name':'userdata','first_lba':8*1024**3//4096,
                  'last_lba':end,'bytes':(end+1-8*1024**3//4096)*4096}
        unit={'name':'sda','logical_block_bytes':4096,'bytes':disk_bytes,'partitions':[userdata]}
        fixture={'luns':[unit]}
        plan=make_plan(fixture,storage)
        check(plan['status']=='offline-repartition-required',
              f'selected {total} GiB produces an offline partition plan')
        esp,system=plan['partitions_proposed']
        tail=((end+1)//256)*256
        check(esp['bytes']==4*1024**3 and system['bytes']==(total-4)*1024**3 and
              (esp['last_lba']-esp['first_lba']+1)*4096==esp['bytes'] and
              (system['last_lba']-system['first_lba']+1)*4096==system['bytes'] and
              esp['last_lba']+1==system['first_lba'] and system['last_lba']==tail-1<=end and
              plan['userdata_last_lba_proposed']+1==esp['first_lba'] and
              plan['android_userdata_bytes_after']>=16*1024**3,
              f'selected {total} GiB preserves bounded contiguous ESP/system geometry')
        too_large=geometry(select_layout(template,total+16))
        check(make_plan(fixture,too_large)['status']=='needs-review',
              f'selected {total} GiB fixture rejects allocation leaving less than 16 GiB Android')
        unit['partitions'].extend([esp,system])
        userdata['last_lba']=esp['first_lba']-1
        userdata['bytes']=(userdata['last_lba']-userdata['first_lba']+1)*4096
        check(make_plan(fixture,storage)['status']=='existing-layout-candidate',
              f'selected {total} GiB identifies its prepared partition layout')
    check(make_plan({'luns':[]})['status']=='needs-review','missing userdata is not guessed')
    collision={'name':'sda','logical_block_bytes':4096,'bytes':256*1024**3,'partitions':[
        {'number':34,'name':'userdata','first_lba':2097152,'last_lba':50000000,'bytes':1},
        {'number':35,'name':'other','first_lba':50000001,'last_lba':50001000,'bytes':4096000}]}
    check(make_plan({'luns':[collision]})['status']=='needs-review','occupied GPT slot rejected')
    raw=plistlib.dumps({'ProductBuildVersion':'20F66','ProductVersion':'16.5','BuildIdentities':[
        {'Info':{'DeviceClass':'j171ap','RestoreBehavior':'Erase'},'Manifest':{
            'OS':{'Info':{'Path':'OS.dmg'}},'Cryptex1,SystemOS':{'Info':{'Path':'SystemOS.dmg'}}}}]})
    cfg={'buildmanifest_sha256':hashlib.sha256(raw).hexdigest()}
    check(select_components(raw,cfg)['OS']=='OS.dmg','IPSW identity selects correct components')
    try: select_components(raw+b'bad',cfg)
    except ValueError: passed.append('wrong IPSW manifest rejected')
    else: raise AssertionError('bad manifest accepted')
    with tempfile.TemporaryDirectory(prefix='nabu224-offline-') as directory:
        tmp=Path(directory)
        data=bytearray(4096);data[32:36]=b'NXSB';struct.pack_into('<IQ',data,36,4096,1)
        image=tmp/'synthetic.apfs';image.write_bytes(data)
        validate_raw(image,{'bytes':4096,'sha256':hashlib.sha256(data).hexdigest()})
        passed.append('synthetic APFS byte length, geometry and digest checked')
        data[32:36]=b'BAD!';image.write_bytes(data)
        try: validate_raw(image,{'bytes':4096,'sha256':hashlib.sha256(data).hexdigest()})
        except ValueError: passed.append('non-APFS wrapper rejected')
        else: raise AssertionError('bad APFS magic accepted')
    for name in ['scan_target','import_system','bind_existing_layout','prepare_target_identity',
                 'prepare_chain','stage_nabu_boot_chain','run_nabu_temporary_boot',
                 'install_ipados_windows','nabu_runtime_logs','fetch_full_ipsw']:
        subprocess.run([sys.executable,str(ROOT/'tools'/f'{name}.py'),'--help'],check=True,stdout=subprocess.DEVNULL)
    passed.append('ten command-line help entries execute without a device')
    template=json.loads((ROOT/'system/transfer-files.template.json').read_text())
    check([x['filename'] for x in template['files']]==['20F66-OS.apfs','20F66-SystemOS.apfs'],
          'system manifest requires only the two user-supplied APFS containers')
    # Synthetic identity and synthetic log receipt are confined to a temporary
    # offline fixture. They are never target inventory or deployment evidence.
    with tempfile.TemporaryDirectory(prefix='nabu224-chain-fixture-') as directory:
        tmp=Path(directory)
        (tmp/'wifi.bin').write_bytes(bytes.fromhex('020000000224'))
        (tmp/'bt.bin').write_bytes(bytes.fromhex('240200000002'))
        (tmp/'nonce.bin').write_bytes(bytes(range(16)))
        (tmp/'label.txt').write_text('OFFLINETEST224')
        (tmp/'power.json').write_text(json.dumps({'device':'nabu','rtc_offset_seconds':1700000000,
            'soc_identity':{'soc_id':339,'serial_number':224}}))
        for script,args in [
            ('prepare_nabu_bluetooth_firmware.py',['--firmware',str(ROOT/'firmware/nabu-wireless'),
             '--address-hci',str(tmp/'bt.bin'),'--rom-version',str(ROOT/'reference/bluetooth-rom-reference.json'),
             '--output',str(tmp/'bluetooth')]),
            ('prepare_nabu_modem_firmware.py',['--firmware',str(ROOT/'firmware/nabu-wireless'),'--output',str(tmp/'modem')])]:
            subprocess.run([sys.executable,str(ROOT/'tools'/script),*args],check=True,stdout=subprocess.DEVNULL)
        from nabu_log_format import slot_offset,SLOT_BYTES
        receipt={'status':'prepared-and-readback-verified','slot':1,'run_uuid':'0'*32,
                 'kernel_sha256':'b5504d908bf5caad31c614c45eb99df3c5e6323f840fcb461ca729a316bb6bda',
                 'manifest_sha256':'0'*64,'slot_offset':slot_offset(1),'slot_bytes':SLOT_BYTES,
                 'fixture_only':True}
        (tmp/'log-fixture.json').write_text(json.dumps(receipt))
        command=[sys.executable,str(ROOT/'tools/stage_nabu_boot_chain.py'),
          '--output',str(tmp/'chain'),'--kernel',str(ROOT/'artifacts/nabu-gpu-ready-v223/kernel.native-apfs.macho'),
          '--bootstrap',str(ROOT/'artifacts/nabu-bootstrap-gpu-v224-context-timer/bootstrap.apfs'),
          '--config',str(ROOT/'configs/nabu-unixnu.toml'),'--checkpoint','0',
          '--wifi-mac-file',str(tmp/'wifi.bin'),'--userland-model','iPad7,11','--userland-serial-file',str(tmp/'label.txt'),
          '--touch-firmware-dir',str(ROOT/'firmware/nabu-touch'),'--image4-nonce-key-file',str(tmp/'nonce.bin'),
          '--rtc-calibration',str(tmp/'power.json'),'--platform-identity',str(tmp/'power.json'),
          '--log-preparation',str(tmp/'log-fixture.json'),'--native-usb',
          '--bluetooth-firmware',str(tmp/'bluetooth'),'--bluetooth-transport','--modem-firmware',str(tmp/'modem'),
          '--modem-glink','--wlan-firmware',str(ROOT/'firmware/nabu-wireless/wlanmdsp.mbn'),
          '--servreg',str(ROOT/'firmware/nabu-wireless/servreg'),'--wlan-qmi','--wlan-msa',
          '--wlan-board',str(ROOT/'firmware/nabu-wireless/bd_k82c.bin'),'--wlan-native-service',
          '--adsp-trial','--gpu-firmware',str(ROOT/'firmware/adreno640')]
        subprocess.run(command,check=True,stdout=subprocess.DEVNULL,cwd=ROOT)
        chain=json.loads((tmp/'chain/chain-manifest.json').read_text())
        check(chain['status']=='prepared' and len(chain['files'])==6,'offline EFI chain with synthetic identity assembles')
        config=tomllib.loads((tmp/'chain/EFI/UniXNU/unixnu.toml').read_text())
        args=next(x['args'] for x in config['entry'] if x['id']=='nabu8796').split()
        check(all(x in args for x in ['nabu-gpu=1','nabu-usb-native=1','nabu-gpu-khz=675000','fb_hz=120']),
              'assembled chain retains GPU224 frequency, display and USB options')
        from inspect_early_boot import inspect_chain
        diagnostic = inspect_chain(tmp/'chain')
        check(diagnostic['adt']['nabu_handoff_inputs_valid'] and
              diagnostic['kernel_callback'] == {'marker_count': 1, 'unset_on_disk': True},
              'GPU224 chain contains the nabu handoff contract and unbound kernel callback slot')
        from nabu_storage_layout import geometry, select_layout, LEGACY, require_kernel_capacity
        template=json.loads((ROOT/'configs/nabu-storage-layout.json').read_text())
        storage=geometry(select_layout(template,128))
        dynamic_kernel=ROOT/'artifacts/nabu-dynamic-storage/kernel.native-apfs.macho'
        kernel_cases=json.loads((dynamic_kernel.parent/'loader-window/report.json').read_text())['cases']
        kernel_sha=next(row['sha256'] for row in kernel_cases if row['name']=='candidate')
        receipt.update(kernel_sha256=kernel_sha,format_version=3,span=1,
                       storage_geometry=storage.record(),slot_offset=slot_offset(1,storage))
        (tmp/'log-fixture.json').write_text(json.dumps(receipt))
        dynamic_command=list(command)
        dynamic_command[dynamic_command.index('--output')+1]=str(tmp/'dynamic-chain')
        dynamic_command[dynamic_command.index('--kernel')+1]=str(dynamic_kernel)
        subprocess.run(dynamic_command,check=True,stdout=subprocess.DEVNULL,cwd=ROOT)
        dynamic_chain=json.loads((tmp/'dynamic-chain/chain-manifest.json').read_text())
        check(dynamic_chain['status']=='prepared' and
              dynamic_chain['runtime_log_preparation']['storage_geometry']==storage.record(),
              'dynamic kernel chain binds the selected 128 GiB installation and v3 log receipt')
        check(inspect_chain(tmp/'dynamic-chain')['adt']['nabu_handoff_inputs_valid'],
              'dynamic kernel retains GPU224 early screen handoff diagnostics')
        try: require_kernel_capacity(ROOT/'artifacts/nabu-gpu-ready-v223/kernel.native-apfs.macho',storage)
        except ValueError: passed.append('original GPU224 kernel rejected for selected capacity')
        else: raise AssertionError('original kernel accepted for a dynamic installation')
    forbidden=[ROOT/'system/20F66-OS.apfs',ROOT/'system/20F66-SystemOS.apfs',
               ROOT/'device/target',ROOT/'device/reclaimed-region.json',ROOT/'target-inputs/personalized']
    check(all(not p.exists() for p in forbidden),'distribution excludes system images and target-owned data')
    report={'status':'offline-checks-passed','checks':passed,'count':len(passed),
            'device_operations_performed':False,'second_tablet_tested':False,
            'full_ipsw_extraction_repeated':False,'partition_executor_included':False,
            'limits':['The planner is not a filesystem resizer.','Firmware and layout need destination evidence.',
                      'Actual install/deploy/boot/recovery remain untested on the second tablet.']}
    (ROOT/'package-check.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({'status':report['status'],'checks':len(passed),'device_operations_performed':False}))

if __name__=='__main__': main()
