"""Select space for a NEW installation on this PC; no device or partition writes."""
import argparse
import json
from pathlib import Path
from nabu_storage_layout import select_layout, geometry
ROOT=Path(__file__).resolve().parents[1]


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--total-gib',type=int,help='Total iPadOS space, including 4 GiB ESP; minimum 32')
    p.add_argument('--output',type=Path,default=ROOT/'configs/selected-layout.json')
    a=p.parse_args()
    if (ROOT/'device/reclaimed-region.json').exists():
        p.error('This folder is already bound to a tablet. Capacity selection is for a fresh kit/new installation.')
    total=a.total_gib
    if total is None:
        total=int(input('Total iPadOS space in GiB (64/128/256 or custom, minimum 32) [64]: ').strip() or '64')
    cfg=select_layout(json.loads((ROOT/'configs/nabu-storage-layout.json').read_text()),total)
    a.output.parent.mkdir(parents=True,exist_ok=True)
    with a.output.open('x',encoding='utf-8') as stream:
        json.dump(cfg,stream,ensure_ascii=False,indent=2);stream.write('\n')
    g=geometry(cfg)
    print(json.dumps({'total_gib':total,'esp_gib':4,'system_partition_gib':total-4,
                      'system_area_gib':10,'data_gib':g.data_bytes//1024**3,'log_gib':1,
                      'layout':str(a.output),'device_writes':False},indent=2))


if __name__=='__main__': main()
