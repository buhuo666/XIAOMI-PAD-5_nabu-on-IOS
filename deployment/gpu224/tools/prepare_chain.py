"""Build GPU224's target-specific chain, optionally deploy to its existing ESP."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
from make_nabu_adt import CHECKPOINTS
ROOT = Path(__file__).resolve().parents[1]

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--gpt-backup',type=Path,required=True)
    p.add_argument('--log-preparation',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--kernel',type=Path,default=ROOT/'artifacts/nabu-dynamic-storage/kernel.native-apfs.macho')
    p.add_argument('--checkpoint', type=int, choices=CHECKPOINTS, default=0,
                   help='Intentional early screen stop; start with 1, then 5/12/17/21. 0 boots normally.')
    p.add_argument('--config', type=Path, default=ROOT/'configs/nabu-unixnu.toml',
                   help='Boot menu template; defaults to the original GPU224 configuration.')
    p.add_argument('--apply',action='store_true')
    a=p.parse_args()
    owned=ROOT/'target-inputs/personalized'
    receipt=json.loads((owned/'receipt.json').read_text())
    inv=json.loads((ROOT/'device/target/inventory.json').read_text())
    if receipt['device_serial_sha256']!=inv['device_serial_sha256']:
        raise ValueError('Personalized input belongs to another device.')
    args=[sys.executable,str(ROOT/'tools/stage_nabu_boot_chain.py'),
        '--output',str(a.output),'--kernel',str(a.kernel),
        '--bootstrap',str(ROOT/'artifacts/nabu-bootstrap-gpu-v224-context-timer/bootstrap.apfs'),
        '--checkpoint',str(a.checkpoint),'--gpt-backup',str(a.gpt_backup),
        '--wifi-mac-file',str(owned/'wifi-mac.bin'),'--userland-model','iPad7,11',
        '--userland-serial-file',str(owned/'compatibility-label.txt'),
        '--log-preparation',str(a.log_preparation),'--touch-firmware-dir',str(ROOT/'firmware/nabu-touch'),
        '--image4-nonce-key-file',str(owned/'image4-nonce-key.bin'),
        '--rtc-calibration',str(owned/'power-and-identity.json'),'--platform-identity',str(owned/'power-and-identity.json'),
        '--native-usb','--bluetooth-firmware',str(owned/'bluetooth'),'--bluetooth-transport',
        '--modem-firmware',str(owned/'modem'),'--modem-glink',
        '--wlan-firmware',str(owned/'wireless-original/wlanmdsp.mbn'),
        '--rmtfs-snapshot',str(owned/'rmtfs'),'--servreg',str(ROOT/'firmware/nabu-wireless/servreg'),
        '--wlan-qmi','--wlan-msa','--wlan-board',str(owned/'wireless-original/bd_k82c.bin'),
        '--wlan-native-service','--adsp-trial','--gpu-firmware',str(owned/'gpu'),
        '--config',str(a.config)]
    if a.apply: args.append('--apply')
    subprocess.run(args,check=True,cwd=ROOT)

if __name__=='__main__':
    main()
