#include <array>
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>
enum chip {A6XX=6,A7XX=7};
enum pipe_format {PIPE_FORMAT_RGBA,PIPE_FORMAT_BGRA,PIPE_FORMAT_X24S8_UINT,PIPE_FORMAT_Z24X8_UNORM,PIPE_FORMAT_Z24_UNORM_S8_UINT,PIPE_FORMAT_R16};
enum a6xx_format {FMT6_ORIGINAL=101,FMT6_Z24_UNORM_S8_UINT_AS_R8G8B8A8=102,FMT6_8_8_8_8_UNORM=103};
enum {WZYX=0,WXYZ=1,XYZW=2,ZYXW=3,X=0,Y=1,Z=2,W=3};
enum VkFilter {VK_FILTER_NEAREST=0,VK_FILTER_LINEAR=1};
constexpr unsigned FDL6_TEX_CONST_DWORDS=16;
struct tu_cmd_buffer{};
struct tu_cs{std::array<uint32_t,16> descriptor{};uint64_t offset=0,ubwc_offset=0;VkFilter filter=VK_FILTER_NEAREST;};
struct view {uint32_t descriptor[16]{};enum pipe_format format=PIPE_FORMAT_RGBA;bool ubwc_enabled=false,is_mutable=false;uint64_t layer_size=65536,ubwc_layer_size=4096;};
struct tu_image_view {struct view view;};
template<chip> void tu_desc_set_format(uint32_t*d,a6xx_format v){d[0]=v;}
template<chip> void tu_desc_set_swap(uint32_t*d,uint32_t v){d[1]=v;}
template<chip> void tu_desc_set_swiz(uint32_t*d,uint32_t v){d[2]=v;}
uint32_t tu_swiz(unsigned a,unsigned b,unsigned c,unsigned d){return a|(b<<3)|(c<<6)|(d<<9);}
template<chip> void r3d_src_common(tu_cmd_buffer*,tu_cs*c,uint32_t*d,uint64_t offset,uint64_t ubwc,VkFilter filter){
    memcpy(c->descriptor.data(),d,64);c->offset=offset;c->ubwc_offset=ubwc;c->filter=filter;
}
#include "actual.inc"
static uint64_t cases=0,unchanged=0,changed=0,channel_checks=0;
static std::array<uint8_t,4> order(std::array<uint8_t,4>a,unsigned swap){
    switch(swap){case 0:return a;case 1:return {a[2],a[1],a[0],a[3]};case 2:return {a[3],a[2],a[1],a[0]};default:return {a[1],a[2],a[3],a[0]};}
}
template<chip C> void test(){
    tu_cmd_buffer cmd;
    for(unsigned format=0;format<6;format++)for(unsigned mutable_image=0;mutable_image<2;mutable_image++)
    for(unsigned ubwc=0;ubwc<2;ubwc++)for(unsigned swap=0;swap<4;swap++)for(unsigned layer:{0u,1u,7u})for(unsigned filter=0;filter<2;filter++)for(unsigned gmem=0;gmem<2;gmem++){
        tu_image_view image;auto&v=image.view;v.format=(pipe_format)format;v.is_mutable=mutable_image;v.ubwc_enabled=ubwc;
        for(unsigned i=0;i<16;i++)v.descriptor[i]=0xa5000000+i;
        v.descriptor[0]=FMT6_ORIGINAL;v.descriptor[1]=swap;v.descriptor[2]=0x1234;
        auto original=v;tu_cs old,now;
        baseline::r3d_src_load<C>(&cmd,&old,&image,layer,(VkFilter)filter,gmem);
        candidate::r3d_src_load<C>(&cmd,&now,&image,layer,(VkFilter)filter,gmem);
        assert(!memcmp(&v,&original,sizeof(v)));
        unsigned expected_swap=gmem&&!mutable_image?0:swap;assert(now.descriptor[1]==expected_swap);
        bool d24=format>=2&&format<=4;
        assert(now.descriptor[0]==(d24?(ubwc?FMT6_Z24_UNORM_S8_UINT_AS_R8G8B8A8:FMT6_8_8_8_8_UNORM):FMT6_ORIGINAL));
        assert(now.descriptor[2]==tu_swiz(X,Y,Z,W));
        for(unsigned i=3;i<16;i++)assert(now.descriptor[i]==original.descriptor[i]);
        assert(now.offset==layer*v.layer_size&&now.ubwc_offset==layer*v.ubwc_layer_size&&now.filter==(VkFilter)filter);
        assert(old.offset==now.offset&&old.ubwc_offset==now.ubwc_offset&&old.filter==now.filter);
        for(unsigned i=0;i<16;i++)if(i!=1)assert(old.descriptor[i]==now.descriptor[i]);
        bool difference=old.descriptor!=now.descriptor;assert(difference==(gmem&&mutable_image&&swap!=0));
        cases++;if(difference)changed++;else unchanged++;
        for(unsigned value=0;value<256;value++){
            std::array<uint8_t,4> memory={(uint8_t)value,(uint8_t)(value^0x31),(uint8_t)(value^0x79),(uint8_t)(value^0xff)};
            auto result=order(memory,now.descriptor[1]);
            auto expected=(gmem&&!mutable_image)?memory:order(memory,swap);
            assert(result==expected);channel_checks++;
        }
        tu_cs wrapper;
        if(gmem){candidate::r3d_src_gmem_load<C>(&cmd,&wrapper,&image,layer);assert(wrapper.filter==VK_FILTER_NEAREST);}
        else{candidate::r3d_src_sysmem_load<C>(&cmd,&wrapper,&image,layer,(VkFilter)filter);}
        assert(wrapper.descriptor==now.descriptor);
    }
    // Reproduce the observed blue -> red with mutable BGRA, while the new
    // descriptor preserves the same channel transform as ordinary sampling.
    tu_image_view image;image.view.is_mutable=true;image.view.format=PIPE_FORMAT_BGRA;image.view.descriptor[1]=WXYZ;
    tu_cs old,now;baseline::r3d_src_gmem_load<C>(&cmd,&old,&image,0);candidate::r3d_src_gmem_load<C>(&cmd,&now,&image,0);
    std::array<uint8_t,4> blue_bgra={255,0,0,255};
    const std::array<uint8_t,4> red_rgba={255,0,0,255},blue_rgba={0,0,255,255};
    assert(order(blue_bgra,old.descriptor[1])==red_rgba);assert(order(blue_bgra,now.descriptor[1])==blue_rgba);
}
int main(){test<A6XX>();test<A7XX>();std::printf("{\"passed\":true,\"actual_function_cases\":%llu,\"unchanged_cases\":%llu,\"changed_mutable_gmem_cases\":%llu,\"channel_checks\":%llu,\"d24_fixup_layer_ubwc_filter_preserved\":true}\n",(unsigned long long)cases,(unsigned long long)unchanged,(unsigned long long)changed,(unsigned long long)channel_checks);}
