"""Record each ordinary descriptor set once per command buffer."""
import json
from pathlib import Path
import shutil

PATCH = 'nabu-turnip-descriptor-set-dedup.patch'
SOURCE_PATCH = 'turnip-descriptor-set-dedup.patch'

OLD = '''   } else {
      struct tu_descriptor_set **record = (struct tu_descriptor_set **)
         util_dynarray_grow(&cmd->resource_descriptor_sets, struct tu_descriptor_set *, 1);
      if (!record) {
         vk_command_buffer_set_error(&cmd->vk, VK_ERROR_OUT_OF_HOST_MEMORY);
         return;
      }

      *record = set;
   }

   if (set->layout->binding_flags'''

NEW = '''   } else {
      /* Submission reads each ordinary set's current resource table. Rebinding
       * the same set needs no second copy of that table in the submission. */
      bool recorded = false;
      util_dynarray_foreach (&cmd->resource_descriptor_sets, struct tu_descriptor_set *, previous) {
         if (*previous == set) {
            recorded = true;
            break;
         }
      }
      if (!recorded) {
         struct tu_descriptor_set **record = (struct tu_descriptor_set **)
            util_dynarray_grow(&cmd->resource_descriptor_sets, struct tu_descriptor_set *, 1);
         if (!record) {
            vk_command_buffer_set_error(&cmd->vk, VK_ERROR_OUT_OF_HOST_MEMORY);
            return;
         }

         *record = set;
      }
   }

   if (set->layout->binding_flags'''


def transform(source, reverse=False):
    before, after = (NEW, OLD) if reverse else (OLD, NEW)
    if source.count(before) != 1:
        raise ValueError('Descriptor recording site differs from the pinned source')
    return source.replace(before, after, 1)


def stage_descriptor_set_dedup(root: Path, work: Path):
    relative = 'patches/mesa/' + PATCH
    shutil.copyfile(root / 'patches/nabu-vulkan' / SOURCE_PATCH, work / relative)
    path = work / 'scripts/data/adreno-compiler-inputs.json'
    pins = json.loads(path.read_text())
    pins['patches'].append(relative)
    path.write_text(json.dumps(pins, indent=2) + '\n', encoding='utf-8', newline='\n')
    return {'patch': relative, 'scope': 'one command buffer; ordinary sets only',
            'change': 'record a bound set pointer once; expand its current resources once at submission',
            'push_descriptors': 'continue recording resources at each binding',
            'lifetime': 'existing resource_descriptor_sets reset and destruction'}
