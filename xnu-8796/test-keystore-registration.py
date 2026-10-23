#!/usr/bin/env python3
"""Check real preprocessed built-in service registration, not kernel execution."""
import argparse, subprocess
from pathlib import Path
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--xnu-source',type=Path,required=True)
p.add_argument('--cc',default='clang')
a=p.parse_args()
source=a.xnu_source/'iokit/KernelConfigTables.cpp'
for defines,expected in [(['-DARM64_BOARD_CONFIG_NABU=1'],1),([],0)]:
 result=subprocess.run([a.cc,'-E','-P','-x','c++',*defines,str(source)],check=True,capture_output=True,text=True).stdout
 assert result.count("'IOClass'         = AppleKeyStore;")==expected, 'AppleKeyStore absent or duplicated for configuration '+str(defines)
 if expected:
  assert "'IOProviderClass' = IOResources;" in result
  assert "'IOMatchCategory' = AppleKeyStore;" in result
print('AppleKeyStore registration: NABU present once; unrelated board unchanged')
