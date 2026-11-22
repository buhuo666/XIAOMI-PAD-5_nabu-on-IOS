"""Stage CPU-only draw/dependency attribution on the retained r25 Turnip."""
import json
from pathlib import Path
import shutil


def stage_gmem_attribution(root: Path, work: Path):
    name='nabu-turnip-gmem-attribution.patch'
    relative='patches/mesa/'+name
    shutil.copyfile(root/'patches/nabu-vulkan'/name,work/relative)
    path=work/'scripts/data/adreno-compiler-inputs.json'
    pins=json.loads(path.read_text())
    pins['patches'].append(relative)
    path.write_text(json.dumps(pins,indent=2)+'\n',newline='\n')
    return dict(patch=relative,scope='common dynamic draw state, LRZ reasons, raw dependencies and trace transport CPU',
                gpu_commands_added=0,per_draw_gpu_timestamps_added=False,
                rendering_policy_changed=False,hardware_stall_counters=False,
                limitation='State and dependency records explain chosen work; they do not measure shader-only or bandwidth-stall time.')
