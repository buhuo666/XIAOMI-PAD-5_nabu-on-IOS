// SPDX-License-Identifier: MIT
// Whole render-pass inputs at the actual encoder entry, observed without
// changing the pass, resource ownership, backend calls or result.
namespace NabuMetalAttachments {
constexpr uint64_t Schema=2;
constexpr uint64_t Begin=512,Command=513,Size=514,Layout=515,Clock=516,End=517,Result=518;
constexpr uint64_t AttachmentBase=544,FieldsPerAttachment=8,AttachmentCount=10;
constexpr uint64_t SlotMask=(1ull<<AttachmentCount)-1;
enum Refusal : uint64_t {None=0,ForeignColor=1,ForeignDepthStencil=2,ForeignVisibility=3,EncoderRefused=4};
struct Pass {
    uint64_t descriptor=0,commandBuffer=0,commitAtEntry=0;
    uint64_t width=0,height=0,arrayLength=0,defaultRasterSamples=0,committed=0;
};
struct Attachment {
    uint64_t descriptor=0,texture=0,resolveTexture=0;
    uint64_t samples=0,resolveSamples=0;
    uint64_t level=0,slice=0,depthPlane=0;
    uint64_t resolveLevel=0,resolveSlice=0,resolveDepthPlane=0;
    uint64_t load=0,store=0,storeOptions=0;
};
class Scope {
    const bool enabled_;
    const uint64_t identity_;
    uint64_t encoder_=0,refusal_=0;
    unsigned slots_=0,activeSlots_=0;
    bool resultKnown_=false;
    void mark(uint64_t stage,uint64_t b,uint64_t c) const {
        if(!enabled_)return;
        const int saved=errno;
        nabu_ca_trace_marker(127,identity_,stage,b,c);
        errno=saved;
    }
public:
    Scope(uint64_t apiIdentity,bool enabled,const Pass &pass):enabled_(enabled),identity_(apiIdentity) {
        if(!enabled_)return;
        const int saved=errno;
        const uint64_t began=nowUs();
        mark(Begin,Schema,pass.descriptor);
        mark(Command,pass.commandBuffer,pass.commitAtEntry);
        mark(Size,pass.width,pass.height);
        mark(Layout,pass.arrayLength,pass.defaultRasterSamples);
        mark(Clock,began,pass.committed);
        errno=saved;
    }
    void attachment(unsigned slot,const Attachment &input) {
        if(!enabled_)return;
        const uint64_t stage=AttachmentBase+uint64_t(slot)*FieldsPerAttachment;
        slots_|=1u<<slot;
        const uint64_t present=(input.descriptor?1:0)|(input.texture?2:0)|(input.resolveTexture?4:0);
        mark(stage,input.descriptor,present);
        // Every slot keeps its presence record. Only texture-bearing slots
        // need the seven detailed rows; omitted fields remain unobserved.
        if(!(present&6))return;
        activeSlots_|=1u<<slot;
        mark(stage+1,input.texture,input.resolveTexture);
        mark(stage+2,input.samples,input.resolveSamples);
        mark(stage+3,input.level,input.slice);
        mark(stage+4,input.depthPlane,input.resolveLevel);
        mark(stage+5,input.resolveSlice,input.resolveDepthPlane);
        mark(stage+6,input.load,input.store);
        mark(stage+7,input.storeOptions,0);
    }
    void result(uint64_t encoder,Refusal refusal=None) {
        encoder_=encoder;refusal_=refusal;resultKnown_=true;
    }
    ~Scope() {
        if(!enabled_)return;
        const int saved=errno;
        const uint64_t ended=nowUs();
        mark(End,ended,(resultKnown_?1ull:0ull)|(encoder_?2ull:0ull)|
            ((uint64_t(slots_)&SlotMask)<<8)|((uint64_t(activeSlots_)&SlotMask)<<24));
        mark(Result,encoder_,refusal_);
        errno=saved;
    }
    Scope(const Scope &)=delete;
    Scope &operator=(const Scope &)=delete;
};
#ifdef __OBJC__
static Pass pass(MTLRenderPassDescriptor *descriptor,uint64_t commandBuffer,uint64_t commit,bool committed) {
    Pass out;
    out.descriptor=(uint64_t)(uintptr_t)(__bridge void *)descriptor;
    out.commandBuffer=commandBuffer;out.commitAtEntry=commit;out.committed=committed;
    out.width=descriptor.renderTargetWidth;out.height=descriptor.renderTargetHeight;
    out.arrayLength=descriptor.renderTargetArrayLength;out.defaultRasterSamples=descriptor.defaultRasterSampleCount;
    return out;
}
static Attachment attachment(MTLRenderPassAttachmentDescriptor *descriptor) {
    Attachment out;
    id<MTLTexture> texture=descriptor.texture,resolve=descriptor.resolveTexture;
    out.descriptor=(uint64_t)(uintptr_t)(__bridge void *)descriptor;
    out.texture=(uint64_t)(uintptr_t)(__bridge void *)texture;
    out.resolveTexture=(uint64_t)(uintptr_t)(__bridge void *)resolve;
    if(!texture&&!resolve)return out;
    out.samples=texture.sampleCount;out.resolveSamples=resolve.sampleCount;
    out.level=descriptor.level;out.slice=descriptor.slice;out.depthPlane=descriptor.depthPlane;
    out.resolveLevel=descriptor.resolveLevel;out.resolveSlice=descriptor.resolveSlice;out.resolveDepthPlane=descriptor.resolveDepthPlane;
    out.load=descriptor.loadAction;out.store=descriptor.storeAction;out.storeOptions=descriptor.storeActionOptions;
    return out;
}
#endif
} // namespace NabuMetalAttachments
