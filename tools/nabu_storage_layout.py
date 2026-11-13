"""One capacity contract shared by planning, installation and log recovery."""
from dataclasses import dataclass
import copy
import json
from pathlib import Path
import struct

GIB=1024**3
LEGACY_ID='nabu-20F66-persistent-v1'
DYNAMIC_ID='nabu-20F66-dynamic-v2'
DYNAMIC_MAGIC=b'NABUDYN2'
ROOT_BYTES=10*GIB
LOG_BYTES=GIB
ESP_BYTES=4*GIB


@dataclass(frozen=True)
class Geometry:
    partition_bytes: int=60*GIB
    dynamic: bool=False

    def __post_init__(self):
        if (type(self.partition_bytes) is not int or type(self.dynamic) is not bool or
            self.partition_bytes<28*GIB or self.partition_bytes%GIB or self.partition_bytes//4096>0xffffffff or
            (not self.dynamic and self.partition_bytes!=60*GIB)):
            raise ValueError('Invalid storage geometry: new installs need >=32 GiB total, in whole GiB.')

    @property
    def reserved_offset(self): return self.partition_bytes-LOG_BYTES
    @property
    def data_bytes(self): return self.partition_bytes-ROOT_BYTES-LOG_BYTES
    def record(self): return {'partition_bytes':self.partition_bytes,'dynamic':self.dynamic}
    def manifest_version(self,span): return 3 if self.dynamic else 1 if span==1 else 2


LEGACY=Geometry()


def geometry(cfg):
    if cfg['id'] not in (LEGACY_ID,DYNAMIC_ID): raise ValueError('Unsupported storage layout')
    value=Geometry(cfg['partition_bytes'],cfg['id']==DYNAMIC_ID)
    if (cfg['partition_name']!='nabu_system' or cfg['logical_block_bytes']!=4096 or
        cfg['root_image_bytes']!=ROOT_BYTES or cfg['data']['offset']!=ROOT_BYTES or
        cfg['data']['bytes']!=value.data_bytes or cfg['reserved']['offset']!=value.reserved_offset or
        cfg['reserved']['bytes']!=LOG_BYTES):
        raise ValueError('OS/Data/log geometry differs from the capacity contract')
    return value


def receipt_geometry(receipt):
    item=receipt.get('storage_geometry')
    return Geometry(**item) if item is not None else LEGACY


def default_layout(root):
    selected=Path(root)/'configs/selected-layout.json'
    return selected if selected.is_file() else Path(root)/'configs/nabu-storage-layout.json'


def select_layout(template,total_gib):
    if type(total_gib) is not int: raise ValueError('Capacity must be a whole number of GiB')
    value=Geometry((total_gib-4)*GIB,True)
    cfg=copy.deepcopy(template)
    cfg.update(id=DYNAMIC_ID,partition_bytes=value.partition_bytes)
    cfg['data']['bytes']=value.data_bytes
    cfg['reserved']['offset']=value.reserved_offset
    cfg['data']['purpose']='Empty APFS Data for a new installation; size selected on the deployment computer'
    cfg['reserved']['purpose']='Append-only runtime logs; final 1 GiB of this installation'
    geometry(cfg)
    return cfg


def extension(cfg):
    value=geometry(cfg)
    if not value.dynamic: return bytes(48)
    return DYNAMIC_MAGIC+struct.pack('<5Q',value.partition_bytes,ROOT_BYTES,value.data_bytes,
                                    value.reserved_offset,LOG_BYTES)


def require_kernel_capacity(kernel,value):
    if value.dynamic and b'NABU STORAGE ABI: NABUDYN2' not in Path(kernel).read_bytes():
        raise ValueError('Selected layout requires the dynamic-capacity kernel, not the original GPU224 kernel.')
