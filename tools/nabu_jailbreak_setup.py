#!/usr/bin/env python3
"""Stage reviewed setup inputs or read native setup reports through paired USB."""
import argparse
import json
from pathlib import Path
import plistlib
import struct
from install_nabu_test_app import AFC
from probe_apple_mobile_device import list_mux_devices, utc_now
from probe_nabu_lockdown_session import mux_connect, exchange, tls_context, wrap_pinned
from probe_nabu_system_services import afc_read


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage',action='store_true')
    parser.add_argument('--seed',type=Path)
    parser.add_argument('--inputs',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.stage and (not args.seed or not args.inputs): parser.error('--stage requires --seed and --inputs')
    args.output.mkdir(parents=True,exist_ok=False)
    report=dict(started_utc=utc_now(),action='stage' if args.stage else 'read',files={},reboots_device=False)
    streams=[]
    try:
        device,=[d for d in list_mux_devices()['response']['DeviceList'] if d['Properties']['ConnectionType']=='USB']
        record=plistlib.loads((Path('C:/ProgramData/Apple/Lockdown')/(device['Properties']['SerialNumber']+'.plist')).read_bytes())
        connection=mux_connect(device['DeviceID'],62078); streams.append(connection)
        start=exchange(connection,{'Request':'StartSession','HostID':record['HostID'],'SystemBUID':record['SystemBUID']})
        context=tls_context(record); connection=wrap_pinned(context,connection,record); streams[-1]=connection
        def service(name):
            reply=exchange(connection,{'Request':'StartService','Service':name})
            stream=mux_connect(device['DeviceID'],reply['Port'])
            if reply.get('EnableServiceSSL'):stream=wrap_pinned(context,stream,record)
            streams.append(stream); return stream
        afc=AFC(service('com.apple.afc'))
        if args.stage:
            review=json.loads((args.seed/'input-review.json').read_text())
            metadata=json.loads((args.seed/'seed-metadata-check.json').read_text())
            assert review['ownership_preserved_in_tar'] and metadata['owners_modes_sizes_types_preserved']
            for path in ['/NabuJailbreak','/NabuJailbreak/Inputs']:
                afc.command(0x09,path.encode()+b'\0',accepted=(0,16))
            sources=[args.seed/'prefix.tar.gz',args.inputs/'sileo-2.5.1.deb',args.inputs/'ellekit-0.4.5.deb']
            for source in sources:
                target=('/NabuJailbreak/Inputs/'+source.name).encode()+b'\0'
                handle=afc.command(0x0D,struct.pack('<Q',3)+target)
                try:
                    with source.open('rb') as data:
                        while chunk:=data.read(65536):afc.command(0x10,handle,chunk)
                finally:afc.command(0x14,handle)
                values=afc.command(0x0A,target).rstrip(b'\0').split(b'\0')
                info=dict(zip(values[::2],values[1::2]))
                assert int(info[b'st_size'])==source.stat().st_size
                report['files'][source.name]={'bytes':source.stat().st_size,'remote_size_equal':True}
                print('Staged '+source.name,flush=True)
        else:
            report['staged_inputs']={}
            for name in ['prefix.tar.gz','sileo-2.5.1.deb','ellekit-0.4.5.deb']:
                values=afc.command(0x0A,('/NabuJailbreak/Inputs/'+name).encode()+b'\0').rstrip(b'\0').split(b'\0')
                report['staged_inputs'][name]=int(dict(zip(values[::2],values[1::2]))[b'st_size'])
            try:
                names=afc.command(0x03,b'/NabuJailbreak/Setup\0').decode().split('\0')
            except Exception as error:
                names=[]; report['setup_directory_error']=str(error)
            for name in names:
                if not name.endswith(('.json','.log')) or '/' in name:continue
                data=afc_read(afc,'/NabuJailbreak/Setup/'+name)
                (args.output/name).write_bytes(data)
                report['files'][name]={'bytes':len(data)}
            install=service('com.apple.mobile.installation_proxy')
            report['lookup']=exchange(install,{'Command':'Lookup','ClientOptions':{
                'BundleIDs':['org.nabu.JailbreakSetup','org.coolstar.SileoStore'],
                'ReturnAttributes':['CFBundleIdentifier','CFBundleVersion','CFBundleShortVersionString','Path']}})
        try:
            exchange(connection,{'Request':'StopSession','SessionID':start['SessionID']})
        except OSError as error:
            # A long AFC transfer can outlive Lockdown's idle control session.
            report['stop_session_error']=str(error)
    except Exception as error:report['error']=str(error)
    finally:
        for stream in reversed(streams):stream.close()
        report['finished_utc']=utc_now()
        (args.output/'usb-report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))
    if 'error' in report:raise SystemExit(1)


if __name__=='__main__':main()
