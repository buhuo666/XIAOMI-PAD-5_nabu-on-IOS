"""Deduplicate resource address/size pairs while command streams record them."""
import json
from pathlib import Path
import shutil

HEADER = 'tu_resource_range_index.h'
PATCH = 'nabu-turnip-cs-range-index.patch'

OLD = '''   const uint32_t count = util_dynarray_num_elements(&cs->resource_ranges, struct tu_resource_range);
   struct tu_resource_range *ranges = (struct tu_resource_range *)cs->resource_ranges.data;
   for (uint32_t i = count; i > 0 && count - i < 16; i--) {
      if (ranges[i - 1].iova == iova && ranges[i - 1].size == bytes) {
         ranges[i - 1].access |= access;
         return;
      }
   }

   struct tu_resource_range *range = (struct tu_resource_range *)
      util_dynarray_grow(&cs->resource_ranges, struct tu_resource_range, 1);
   if (!range) {
      tu_cs_set_error(cs, VK_ERROR_OUT_OF_HOST_MEMORY);
      return;
   }
   *range = {iova, bytes, access};'''


def transform(sources, reverse=False):
    result = dict(sources)
    changes = [
        ('tu_cs.h', '#include "tu_knl.h"', '#include "tu_knl.h"\n#include "' + HEADER + '"'),
        ('tu_cs.h', '   struct util_dynarray resource_ranges;',
         '   struct util_dynarray resource_ranges;\n   struct tu_resource_range_index resource_range_index;'),
        ('tu_cs.cc', OLD,
         '   if (!tu_resource_range_index_add(&cs->resource_range_index, &cs->resource_ranges,\n'
         '                                    {iova, bytes, access}))\n'
         '      tu_cs_set_error(cs, VK_ERROR_OUT_OF_HOST_MEMORY);'),
        ('tu_cs.cc', '   util_dynarray_clear(&cs->resource_ranges);',
         '   util_dynarray_clear(&cs->resource_ranges);\n'
         '   tu_resource_range_index_clear(&cs->resource_range_index);'),
        ('tu_cs.cc', '   util_dynarray_fini(&cs->resource_ranges);',
         '   util_dynarray_fini(&cs->resource_ranges);\n'
         '   tu_resource_range_index_finish(&cs->resource_range_index);'),
    ]
    for file, old, new in changes:
        if reverse:
            old, new = new, old
        if result[file].count(old) != 1:
            raise ValueError('CS recording site differs from the pinned source: ' + file)
        result[file] = result[file].replace(old, new, 1)
    return result


def stage_cs_range_index(root: Path, work: Path):
    relative = 'patches/mesa/' + PATCH
    shutil.copyfile(root / 'patches/nabu-vulkan/turnip-cs-range-index.patch', work / relative)
    path = work / 'scripts/data/adreno-compiler-inputs.json'
    pins = json.loads(path.read_text())
    pins['patches'].append(relative)
    path.write_text(json.dumps(pins, indent=2) + '\n', encoding='utf-8', newline='\n')
    return {'patch': relative, 'scope': 'command-stream resource metadata',
            'key': 'exact IOVA and size, union access bits',
            'lifetime': 'CS init zeroes index; reset clears it; finish frees it',
            'gpu_commands_changed': False, 'command_buffer_recording_changed': False}
