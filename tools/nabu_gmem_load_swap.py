"""Keep the image's swap when GMEM uses mutable channel ordering."""
import json,shutil
from pathlib import Path
PATCH='nabu-turnip-gmem-load-swap.patch'
OLD='''   if (override_swap)
      tu_desc_set_swap<CHIP>(desc, WZYX);
   tu_desc_set_swiz<CHIP>(desc, tu_swiz(X, Y, Z, W));'''
NEW='''   /* Mutable GMEM keeps the format's channel ordering, just as
    * r3d_src_gmem() and store_cp_blit() do. Removing the swap here alone
    * makes a shaded load exchange red/blue for a mutable BGRA attachment. */
   if (override_swap && !iview->view.is_mutable)
      tu_desc_set_swap<CHIP>(desc, WZYX);
   tu_desc_set_swiz<CHIP>(desc, tu_swiz(X, Y, Z, W));'''
def transform(source,reverse=False):
    old,new=(NEW,OLD) if reverse else (OLD,NEW)
    start=source.index('r3d_src_load(');end=source.index('\ntemplate <chip CHIP>',start)
    part=source[start:end]
    if part.count(old)!=1:raise ValueError('Pinned GMEM load descriptor site changed')
    return source[:start]+part.replace(old,new,1)+source[end:]
def stage(root:Path,work:Path):
    relative='patches/mesa/'+PATCH
    shutil.copyfile(root/'patches/nabu-vulkan'/PATCH,work/relative)
    path=work/'scripts/data/adreno-compiler-inputs.json';pins=json.loads(path.read_text())
    if relative in pins['patches']:raise ValueError('Duplicate load swap patch')
    pins['patches'].append(relative);path.write_text(json.dumps(pins,indent=2)+'\n',encoding='utf8',newline='\n')
    return {'patch':relative,'scope':'Only r3d_src_load channel swap for mutable GMEM','pitch_policy_preserved':True,'immutable_and_sysmem_paths_unchanged':True}
