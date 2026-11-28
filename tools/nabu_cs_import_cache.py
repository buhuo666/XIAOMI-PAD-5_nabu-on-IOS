"""Stage metadata-only repeated command-stream import elimination."""
import json
from pathlib import Path
import shutil

PATCH='turnip-cs-import-cache.patch'
OLD='''   if (cs == target)
      return;

   util_dynarray_foreach (&target->resource_ranges, struct tu_resource_range, range) {
      tu_cs_use_range(cs, range->iova, range->size, range->access);
   }'''
NEW='''   if (cs == target || cs->mode == TU_CS_MODE_EXTERNAL || cs->record_result != VK_SUCCESS)
      return;

   /* Small lists cost less than looking through the bounded import memo.
    * A source's reset/reuse or any new range/access bit changes its token. */
   const bool memo = util_dynarray_num_elements(&target->resource_ranges,
                                               struct tu_resource_range) >= 16;
   if (memo && tu_resource_range_imported(&cs->resource_range_index,
                                         &target->resource_range_index))
      return;
   util_dynarray_foreach (&target->resource_ranges, struct tu_resource_range, range) {
      tu_cs_use_range(cs, range->iova, range->size, range->access);
   }
   if (memo && cs->record_result == VK_SUCCESS)
      tu_resource_range_note_import(&cs->resource_range_index,
                                   &target->resource_range_index);'''

def transform(text,reverse=False):
    old,new=(NEW,OLD) if reverse else (OLD,NEW)
    if text.count(old)!=1:raise ValueError('Pinned resource-import function changed')
    return text.replace(old,new,1)

def stage(root:Path,work:Path):
    relative='patches/mesa/'+PATCH
    shutil.copyfile(root/'patches/nabu-vulkan'/PATCH,work/relative)
    path=work/'scripts/data/adreno-compiler-inputs.json'
    pins=json.loads(path.read_text());pins['patches'].append(relative)
    path.write_text(json.dumps(pins,indent=2)+'\n')
    return dict(patch=relative,scope='CPU resource metadata only',memo_entries=8,
        source_threshold=16,source_changes_invalidate=True,reset_and_reuse_invalidate=True,
        no_gpu_packet_change=True,no_render_policy_change=True)
