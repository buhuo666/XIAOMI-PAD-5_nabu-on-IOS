"""GPU380: use verified current-mip row padding for imported color attachments."""
import json, shutil
from pathlib import Path

PATCH = 'nabu-turnip-attachment-pitch.patch'
OLD = '''bool
tu_attachment_unpadded(struct tu_cmd_buffer *cmd, const struct tu_image_view *iview)
{
   const struct fd_dev_info *info = cmd->device->physical_device->info;
   const VkExternalMemoryHandleTypeFlags host_types =
      VK_EXTERNAL_MEMORY_HANDLE_TYPE_HOST_ALLOCATION_BIT_EXT |
      VK_EXTERNAL_MEMORY_HANDLE_TYPE_HOST_MAPPED_FOREIGN_MEMORY_BIT_EXT;

   return iview->image->layout[0].tile_mode == TILE6_LINEAR &&
          (iview->image->vk.tiling == VK_IMAGE_TILING_DRM_FORMAT_MODIFIER_EXT ||
           (iview->image->vk.external_handle_types & host_types)) &&
          (iview->view.width % info->gmem_align_w ||
           iview->view.height % info->gmem_align_h);
}'''
NEW = '''bool
tu_attachment_unpadded(struct tu_cmd_buffer *cmd, const struct tu_image_view *iview)
{
   const struct fd_dev_info *info = cmd->device->physical_device->info;
   const struct fdl_layout *layout = &iview->image->layout[0];
   const VkExternalMemoryHandleTypeFlags host_types =
      VK_EXTERNAL_MEMORY_HANDLE_TYPE_HOST_ALLOCATION_BIT_EXT |
      VK_EXTERNAL_MEMORY_HANDLE_TYPE_HOST_MAPPED_FOREIGN_MEMORY_BIT_EXT;

   if (layout->tile_mode != TILE6_LINEAR ||
       !(iview->image->vk.tiling == VK_IMAGE_TILING_DRM_FORMAT_MODIFIER_EXT ||
         (iview->image->vk.external_handle_types & host_types)))
      return false;

   /* Preserve the existing result for full blocks, including ordinary screen
    * targets. Only a width-only edge is eligible for the row-padding proof. */
   if (iview->view.height % info->gmem_align_h)
      return true;
   if (!(iview->view.width % info->gmem_align_w))
      return false;

   /* Keep depth/stencil, multi-plane, reinterpretation and MSAA on the old
    * texel-bounded path. No image allocation or layout policy is changed. */
   if (!iview->view.width || !iview->view.height ||
       iview->image->vk.samples != VK_SAMPLE_COUNT_1_BIT ||
       iview->vk.format != iview->image->vk.format ||
       vk_format_is_depth_or_stencil(iview->image->vk.format) ||
       tu6_plane_count(iview->image->vk.format) != 1 ||
       !(layout->cpp == 1 || layout->cpp == 2 || layout->cpp == 4 ||
         layout->cpp == 8 || layout->cpp == 16))
      return true;

   const uint32_t level = iview->vk.base_mip_level;
   if (level >= layout->mip_levels)
      return true;
   const uint32_t pitch = fdl_pitch(layout, level);
   if (iview->view.pitch != pitch)
      return true;
   /* The final row must fit its entire GMEM block in the owner's row, too.
    * Widen before alignment/multiplication so a large row cannot wrap. */
   const uint64_t reach =
      ALIGN_POT((uint64_t) iview->view.width, (uint64_t) info->gmem_align_w) * layout->cpp;
   return reach > pitch;
}'''

def transform(text, reverse=False):
    old,new=(NEW,OLD) if reverse else (OLD,NEW)
    if text.count(old)!=1:
        raise ValueError('Pinned imported-attachment predicate changed')
    return text.replace(old,new,1)

def stage(root: Path, work: Path):
    relative='patches/mesa/'+PATCH
    shutil.copyfile(root/'patches/nabu-vulkan'/PATCH,work/relative)
    manifest=work/'scripts/data/adreno-compiler-inputs.json'
    pins=json.loads(manifest.read_text())
    if relative in pins['patches']:
        raise ValueError('Attachment pitch patch already staged')
    pins['patches'].append(relative)
    manifest.write_text(json.dumps(pins,indent=2)+'\n',encoding='utf8',newline='\n')
    return dict(patch=relative,scope='imported linear single-sample same-format color row padding',
        current_mip_pitch=True,reach_uses_uint64=True,old_fallbacks_preserved=True,
        force_gmem=False,allocation_policy_changed=False)
