"""Stage the r21 bounded GPU-stage file transport on the qualified Turnip tree."""
import json
from pathlib import Path
import shutil

def stage_bounded_gpu_file(root: Path, work: Path):
    name='nabu-turnip-r21-bounded-file.patch'
    relative='patches/mesa/'+name
    shutil.copyfile(root/'patches/nabu-vulkan'/name, work/relative)
    path=work/'scripts/data/adreno-compiler-inputs.json'
    pins=json.loads(path.read_text());pins['patches'].append(relative)
    path.write_text(json.dumps(pins,indent=2)+'\n',newline='\n')
    return dict(patch=relative, control='existing LastTraceResult capture window',
        gpu_timestamp_budget_per_device=16<<20, file_budget_per_process_per_window=512<<20,
        new_kernel_selectors=False, completed_records_survive_window_end=True,
        limitation='GPU timestamps include drain/backpressure and timestamp overhead; A640 validation pending')
