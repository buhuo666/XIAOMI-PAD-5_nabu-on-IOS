"""Count submission ranges by the source that actually appends them."""
import json
from pathlib import Path
import shutil

PATCH = 'nabu-turnip-resource-origins.patch'


def transform(source, reverse=False):
    replacements = (
        ('   struct util_dynarray native_ranges; /* NativeAdrenoAbiSubmitResourceV2 */\n   VkResult result;',
         '   struct util_dynarray native_ranges; /* NativeAdrenoAbiSubmitResourceV2 */\n'
         '   uint64_t source_cs_ranges, source_cmd_ranges, source_descriptor_ranges;\n'
         '   uint64_t source_descriptor_sets, source_command_buffers;\n'
         '   VkResult result;'),
        ('   memcpy(target, cs->resource_ranges.data, count * sizeof(struct tu_resource_range));',
         '   memcpy(target, cs->resource_ranges.data, count * sizeof(struct tu_resource_range));\n'
         '   submit->source_cs_ranges += count;'),
        ('   submit->fallback_reasons |= cmd->resource_fallback_reasons;',
         '   submit->fallback_reasons |= cmd->resource_fallback_reasons;\n'
         '   submit->source_command_buffers++;'),
        ('      memcpy(target, cmd->resource_ranges.data, count * sizeof(struct tu_resource_range));',
         '      memcpy(target, cmd->resource_ranges.data, count * sizeof(struct tu_resource_range));\n'
         '      submit->source_cmd_ranges += count;'),
        ('      const struct tu_descriptor_set *set = *set_ptr;',
         '      const struct tu_descriptor_set *set = *set_ptr;\n'
         '      submit->source_descriptor_sets++;'),
        ('      memcpy(target, set->resources, set->resource_count * sizeof(*set->resources));',
         '      memcpy(target, set->resources, set->resource_count * sizeof(*set->resources));\n'
         '      submit->source_descriptor_ranges += set->resource_count;'),
        ('      VkResult collected = darwin_collect_submit_resources(dev, submit, caps.version == 0);',
         '      nabuTurnipSubmitMarker((uintptr_t)submit, 53, submit->source_cs_ranges, submit->source_cmd_ranges);\n'
         '      nabuTurnipSubmitMarker((uintptr_t)submit, 54, submit->source_descriptor_ranges, submit->source_descriptor_sets);\n'
         '      nabuTurnipSubmitMarker((uintptr_t)submit, 55, total, submit->source_command_buffers);\n'
         '      VkResult collected = darwin_collect_submit_resources(dev, submit, caps.version == 0);'),
    )
    for old, new in replacements:
        if reverse:
            old, new = new, old
        if source.count(old) != 1:
            raise ValueError('Resource origin site differs from the pinned source: ' + old)
        source = source.replace(old, new, 1)
    return source


def stage_resource_origins(root: Path, work: Path):
    relative = 'patches/mesa/' + PATCH
    shutil.copyfile(root / 'patches/nabu-vulkan/turnip-resource-origins.patch', work / relative)
    path = work / 'scripts/data/adreno-compiler-inputs.json'
    pins = json.loads(path.read_text())
    pins['patches'].append(relative)
    path.write_text(json.dumps(pins, indent=2) + '\n', encoding='utf-8', newline='\n')
    return {'patch': relative, 'event': 127,
            'metadata': {53: 'b=CS ranges,c=command ranges including push snapshots',
                         54: 'b=ordinary descriptor ranges,c=ordinary set references',
                         55: 'b=IB ranges,c=command buffers'},
            'accounting': 'CS + command + ordinary descriptor + IB ranges equals raw range count',
            'scope': 'Three optional markers per submission; no GPU command or resource changes'}
