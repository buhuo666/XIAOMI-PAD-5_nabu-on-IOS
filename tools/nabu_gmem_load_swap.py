"""Preserve the memory-side channel swap in nonmutable shaded GMEM loads."""
import json,shutil
from pathlib import Path
PATCH='nabu-turnip-gmem-load-swap.patch'
OLD='''   r3d_src_load<CHIP>(cmd, cs, iview, layer, VK_FILTER_NEAREST, true);'''
NEW='''   /* This samples the memory side, not GMEM. Nonmutable linear images
    * need their format swap (e.g. BGRA) to produce shader-order colors.
    * Preserve the existing override for mutable tiled views. */
   r3d_src_load<CHIP>(cmd, cs, iview, layer, VK_FILTER_NEAREST,
                       iview->view.is_mutable);'''
def transform(source,reverse=False):
    old,new=(NEW,OLD) if reverse else (OLD,NEW)
    start=source.index('r3d_src_gmem_load(');end=source.index('\ntemplate <chip CHIP>',start)
    part=source[start:end]
    if part.count(old)!=1:raise ValueError('Pinned GMEM load descriptor site changed')
    return source[:start]+part.replace(old,new,1)+source[end:]
def stage(root:Path,work:Path):
    relative='patches/mesa/'+PATCH
    shutil.copyfile(root/'patches/nabu-vulkan'/PATCH,work/relative)
    path=work/'scripts/data/adreno-compiler-inputs.json';pins=json.loads(path.read_text())
    if relative in pins['patches']:raise ValueError('Duplicate load swap patch')
    pins['patches'].append(relative);path.write_text(json.dumps(pins,indent=2)+'\n',encoding='utf8',newline='\n')
    return {'patch':relative,'scope':'Only r3d_src_gmem_load memory-side swap for nonmutable views','pitch_policy_preserved':True,'mutable_and_sysmem_paths_unchanged':True}
