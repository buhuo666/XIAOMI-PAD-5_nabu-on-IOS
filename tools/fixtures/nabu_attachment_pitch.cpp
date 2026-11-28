#include <algorithm>
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <vector>
#include <limits>
using VkExternalMemoryHandleTypeFlags=uint32_t;
constexpr uint32_t VK_EXTERNAL_MEMORY_HANDLE_TYPE_HOST_ALLOCATION_BIT_EXT=1;
constexpr uint32_t VK_EXTERNAL_MEMORY_HANDLE_TYPE_HOST_MAPPED_FOREIGN_MEMORY_BIT_EXT=2;
constexpr uint32_t VK_IMAGE_TILING_DRM_FORMAT_MODIFIER_EXT=3;
constexpr uint32_t VK_SAMPLE_COUNT_1_BIT=1;
constexpr uint32_t TILE6_LINEAR=0;
enum { COLOR=1, DEPTH=2, STENCIL=3, PLANAR=4, OTHER_COLOR=5 };
bool vk_format_is_depth_or_stencil(uint32_t f){return f==DEPTH || f==STENCIL;}
unsigned tu6_plane_count(uint32_t f){return f==PLANAR?2:1;}
template<typename T,typename U> T align(T x,U y){T a=static_cast<T>(y);return (x+a-1)&~(a-1);}
uint32_t u_minify(uint32_t n,unsigned level){return std::max(n>>level,1u);}
#define ALIGN_POT(x,y) align((x),(y))
struct fdl_layout {uint32_t tile_mode=0,pitch0=0,pitchalign=6,mip_levels=6,cpp=4;};
struct fd_dev_info {uint32_t gmem_align_w=16,gmem_align_h=4;};
struct tu_physical_device {fd_dev_info *info;};
struct tu_device {tu_physical_device *physical_device;};
struct image_vk {uint32_t tiling=0,external_handle_types=1,samples=1,format=COLOR;};
struct tu_image {fdl_layout layout[1];image_vk vk;};
struct view_vk {uint32_t base_mip_level=0,format=COLOR;};
struct view_fdl {uint32_t width=0,height=0,pitch=0;bool need_y2_align=false;};
struct tu_image_view {tu_image *image;view_vk vk;view_fdl view;};
struct VkRect2D {struct {uint32_t x=0,y=0;}offset;struct {uint32_t width=0,height=0;}extent;};
struct pass_info {uint32_t num_views=1;};
struct tu_cmd_buffer {
   tu_device *device;
   struct {tu_image_view *attachments[1];bool per_layer_render_area=false,fdm_subsampled=false;pass_info *pass;VkRect2D render_areas[2];}state;
};
static bool debug_unaligned=false;
#define TU_DEBUG(x) debug_unaligned
#include "actual.inc"
struct Test {
   fd_dev_info info;tu_physical_device physical{&info};tu_device device{&physical};
   tu_image image;tu_image_view view{&image,{},{} };pass_info pass;
   tu_cmd_buffer cmd{&device,{{&view},false,false,&pass,{}}};
   void shape(uint32_t w,uint32_t h,uint32_t cpp,uint32_t pitch,unsigned mip=0){
      image.layout[0].cpp=cpp;image.layout[0].pitch0=pitch<<mip;
      view.vk.base_mip_level=mip;view.view={w,h,pitch,false};
      cmd.state.render_areas[0]={{0,0},{w,h}};
   }
};
static uint64_t cases=0,changes=0,pixels=0,bounds=0;
// Independent address oracle: walk every whole block in every row. Never use
// the candidate alignment expression to decide whether the owner row fits.
bool whole_blocks_fit(uint32_t w,uint32_t h,uint32_t cpp,uint32_t pitch,uint32_t aw,uint32_t ah){
   for(uint64_t y=0;y<h;y+=ah){
      if(y+ah>h)return false;
      for(uint64_t x=0;x<w;x+=aw){
         for(uint64_t xx=x;xx<x+aw;xx++)if((xx+1)*cpp>pitch)return false;
      }
   }
   return true;
}
void pixels_and_guards(Test& t){
   auto v=t.view.view;uint32_t cpp=t.image.layout[0].cpp,pitch=v.pitch;
   if(v.width*cpp>pitch || !v.width || !v.height)return;
   const size_t guard=64,layer=static_cast<size_t>(pitch)*v.height;
   std::vector<uint8_t> input(guard+layer*2+guard,0xa5),expected=input,actual=input;
   for(uint32_t y=0;y<v.height;y++)for(uint32_t x=0;x<v.width*cpp;x++){
      size_t at=guard+y*pitch+x;input[at]=static_cast<uint8_t>((y*31+x*17)^0x5c);
      expected[at]=input[at]^0x72;
   }
   bool slow=candidate::tu_attachment_unpadded(&t.cmd,&t.view);
   uint32_t end=v.width;
   if(!slow){end=0;while(end<v.width)end+=t.info.gmem_align_w;}
   assert(static_cast<uint64_t>(end)*cpp<=pitch);
   for(uint32_t y=0;y<v.height;y++)for(uint32_t x=0;x<end*cpp;x++){
      size_t at=guard+y*pitch+x;assert(at<guard+layer);
      actual[at]=input[at]^0x72;
   }
   for(uint32_t y=0;y<v.height;y++)for(uint32_t x=0;x<v.width*cpp;x++){
      assert(actual[guard+y*pitch+x]==expected[guard+y*pitch+x]);pixels++;
   }
   for(size_t i=0;i<guard;i++)assert(actual[i]==0xa5);
   for(size_t i=guard+layer;i<actual.size();i++)assert(actual[i]==0xa5);
   bounds++;
}
int main(){
   for(uint32_t aw:{16u,32u})for(uint32_t ah:{4u,8u})for(uint32_t w=1;w<=129;w++)for(uint32_t h=1;h<=17;h++)
   for(uint32_t cpp:{1u,2u,4u,8u,16u})for(unsigned mip:{0u,1u,3u})for(unsigned pitchchoice=0;pitchchoice<3;pitchchoice++){
      Test t;t.info={aw,ah};uint32_t pitch=align(w*cpp,64u);if(pitchchoice==1)pitch+=64;else if(pitchchoice==2 && pitch>=128)pitch-=64;
      t.shape(w,h,cpp,pitch,mip);bool old=baseline::tu_attachment_unpadded(&t.cmd,&t.view),now=candidate::tu_attachment_unpadded(&t.cmd,&t.view);
      bool independent=whole_blocks_fit(w,h,cpp,pitch,aw,ah);
      bool expect=(h%ah)!=0 || ((w%aw)!=0 && !independent);
      assert(now==expect);assert(!now || old);cases++;
      if(old&&!now){changes++;assert(independent);}
      if(aw==16&&ah==4&&mip==0&&pitchchoice==0&&h==4)pixels_and_guards(t);
   }
   // Imported categories, existing debug/render-area policy and exclusions.
   for(unsigned category=0;category<5;category++)for(unsigned tile:{0u,3u})for(unsigned fmt:{COLOR,DEPTH,STENCIL,PLANAR})
   for(unsigned sample:{1u,4u})for(unsigned mismatch:{0u,1u}){
      Test t;t.shape(13,8,4,64);t.image.vk.external_handle_types=category<3?category:0;t.image.vk.tiling=category==3?3:0;
      t.image.layout[0].tile_mode=tile;t.image.vk.format=fmt;t.view.vk.format=mismatch?OTHER_COLOR:fmt;t.image.vk.samples=sample;
      bool imported=tile==0&&(category==1||category==2||category==3);
      bool eligible=fmt==COLOR&&sample==1&&!mismatch;
      bool value=candidate::tu_attachment_unpadded(&t.cmd,&t.view);assert(value==(imported&&!eligible));cases++;
   }
   Test t;t.shape(13,8,4,64);assert(baseline::tu_attachment_store_unaligned(&t.cmd,0));assert(!candidate::tu_attachment_store_unaligned(&t.cmd,0));
   debug_unaligned=true;assert(candidate::tu_attachment_store_unaligned(&t.cmd,0));debug_unaligned=false;
   t.cmd.state.render_areas[0].offset.x=1;assert(candidate::tu_attachment_store_unaligned(&t.cmd,0));
   t.cmd.state.render_areas[0]={{0,0},{12,8}};assert(candidate::tu_attachment_store_unaligned(&t.cmd,0));
   t.cmd.state.render_areas[0]={{0,0},{13,7}};assert(candidate::tu_attachment_store_unaligned(&t.cmd,0));
   t.cmd.state.per_layer_render_area=true;t.pass.num_views=2;t.cmd.state.render_areas[0]={{0,0},{13,8}};t.cmd.state.render_areas[1]={{1,0},{12,8}};assert(candidate::tu_attachment_store_unaligned(&t.cmd,0));
   t.cmd.state.fdm_subsampled=true;assert(!candidate::tu_attachment_store_unaligned(&t.cmd,0));
   // Nonzero mip must not borrow level zero's room; small/invalid metadata
   // falls back. Full blocks preserve the baseline predicate, even for a
   // deliberately malformed pitch (the normal image validator owns that).
   Test q;q.shape(29,8,8,128,1);assert(candidate::tu_attachment_unpadded(&q.cmd,&q.view));
   q.shape(29,8,8,256,1);assert(!candidate::tu_attachment_unpadded(&q.cmd,&q.view));
   q.view.view.pitch=128;assert(candidate::tu_attachment_unpadded(&q.cmd,&q.view));
   q.view.view.pitch=256;q.view.vk.base_mip_level=6;assert(candidate::tu_attachment_unpadded(&q.cmd,&q.view));
   q.shape(13,8,3,64);assert(candidate::tu_attachment_unpadded(&q.cmd,&q.view));
   q.shape(0xffffffffu,8,16,0xffffffc0u);assert(candidate::tu_attachment_unpadded(&q.cmd,&q.view));
   q.shape(16,8,4,64);assert(candidate::tu_attachment_unpadded(&q.cmd,&q.view)==baseline::tu_attachment_unpadded(&q.cmd,&q.view));
   // Previously seen desktop candidate dimensions and the aligned screen.
   for(auto dimensions:{std::pair{204u,324u},std::pair{284u,132u},std::pair{1836u,256u},std::pair{1836u,576u},std::pair{1600u,2560u}}){
      Test x;x.shape(dimensions.first,dimensions.second,4,align(dimensions.first*4,64u));
      assert(!candidate::tu_attachment_unpadded(&x.cmd,&x.view));
   }
   std::printf("{\"passed\":true,\"policy_cases\":%llu,\"eligible_old_slow_cases\":%llu,\"visible_bytes_compared\":%llu,\"guarded_buffers\":%llu,\"mip_overflow_import_format_sample_render_area_cases\":true}\n",
      (unsigned long long)cases,(unsigned long long)changes,(unsigned long long)pixels,(unsigned long long)bounds);
}
