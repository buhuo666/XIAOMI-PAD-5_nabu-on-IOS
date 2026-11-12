// Host adapters around extracted production Turnip functions.
#include <algorithm>
#include <cassert>
#include <chrono>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <memory>
#include <pthread.h>
#include <tuple>
#include <vector>

using VkResult = int;
constexpr VkResult VK_SUCCESS = 0, VK_ERROR_OUT_OF_HOST_MEMORY = -1;
constexpr uint32_t TU_RESOURCE_READ = 1, TU_RESOURCE_WRITE = 2;
constexpr uint32_t TU_BO_ALLOC_GPU_READ_ONLY = 1;
constexpr uint32_t TU_RESOURCE_FALLBACK_DEVICE_ADDRESS = 1;
constexpr uint32_t DARWIN_NATIVE_BO_LIMIT = 4096, DARWIN_BO_ACTIVE = 1;
#define MAX2(a,b) ((a) > (b) ? (a) : (b))

static int allocation_fail_after = -1;
static uint64_t grows, range_lookups, references, releases;
struct util_dynarray { void *data; size_t size, capacity; };
static void init(util_dynarray *a) {
    a->data = std::malloc(64); assert(a->data); a->size = 0; a->capacity = 64;
}
static void *util_dynarray_grow_bytes(util_dynarray *a, size_t count, size_t element) {
    grows++;
    if (allocation_fail_after == 0) return nullptr;
    if (allocation_fail_after > 0) allocation_fail_after--;
    const size_t extra = count * element, before = a->size;
    if (before + extra > a->capacity) {
        size_t capacity = std::max(before + extra, a->capacity * 2);
        void *next = std::realloc(a->data, capacity);
        if (!next) return nullptr;
        a->data = next; a->capacity = capacity;
    }
    a->size += extra;
    return static_cast<char *>(a->data) + before;
}
static void util_dynarray_fini(util_dynarray *a) { std::free(a->data); *a = {}; }
#define util_dynarray_num_elements(a,T) ((a)->size / sizeof(T))
#define util_dynarray_grow(a,T,n) util_dynarray_grow_bytes((a),(n),sizeof(T))
#define util_dynarray_foreach(a,T,it) \
    for (T *it = static_cast<T *>((a)->data); \
         it < reinterpret_cast<T *>(static_cast<char *>((a)->data) + (a)->size); ++it)

struct NativeAdrenoAbiSubmitBuffer { uint64_t handle, iova, bytes; };
struct NativeAdrenoAbiSubmitResourceV2 { uint64_t handle, offset, bytes; uint32_t access, reserved; };
struct tu_resource_range { uint64_t iova, size; uint32_t access; };
struct tu_bo { uint64_t darwin_handle, iova, size; uint32_t gem_handle, darwin_alloc_flags, refs; };
struct tu_darwin_queue_submit {
    util_dynarray commands, ranges, resources, native_ranges;
    VkResult result;
    uint32_t fallback_reasons;
};
struct darwin_submit_resource { tu_bo *bo; uint32_t access; };
struct rb_node { rb_node *left, *right; };
struct rb_tree { rb_node *root; };
struct darwin_retired_bo { uint64_t iova, size; uint32_t gem_handle; };
struct darwin_bo_node { darwin_retired_bo bo; rb_node active_iova; uint32_t state; };
struct tu_device;
struct darwin_retire_state {
    pthread_mutex_t lock;
    darwin_bo_node nodes[DARWIN_NATIVE_BO_LIMIT + 1];
    rb_tree active_bos;
    tu_device *device;
};
struct tu_device {
    void *darwin_retire;
    tu_bo objects[DARWIN_NATIVE_BO_LIMIT + 1];
    struct { int alloc; } vk;
};
#define rb_node_data(T,p,member) reinterpret_cast<T *>(reinterpret_cast<char *>(p) - offsetof(T,member))
static tu_bo *tu_device_lookup_bo(tu_device *dev, uint32_t id) {
    assert(id && id <= DARWIN_NATIVE_BO_LIMIT); return &dev->objects[id];
}
static tu_bo *tu_bo_get_ref(tu_bo *bo) { assert(bo->refs > 0); bo->refs++; references++; return bo; }
static void tu_bo_finish(tu_device *, tu_bo *bo) { assert(bo->refs > 1); bo->refs--; releases++; }
static void vk_free(int *, void *p) { std::free(p); }

/* ACTUAL_LOOKUP */

static tu_bo *darwin_lookup_bo_locked(darwin_retire_state *retire, uint64_t iova, uint64_t bytes) {
    range_lookups++;
    return actual_darwin_lookup_bo_locked(retire, iova, bytes);
}

// Diagnostic transport does not participate in collector semantics.
struct NabuTurnipSubmitSpan {
    NabuTurnipSubmitSpan(uint64_t, uint64_t, const void *, uint64_t) {}
};
static void nabuTurnipSubmitMarker(uintptr_t, uint64_t, uint64_t, uint64_t) {}

namespace before {
/* ACTUAL_BASELINE */
}
namespace after {
/* ACTUAL_CANDIDATE */
}

/* ACTUAL_CLEANUP */

using Native = std::tuple<uint64_t,uint64_t,uint64_t,uint32_t>;
struct Observation {
    VkResult result;
    uint32_t fallback;
    std::vector<Native> native;
    std::vector<uint64_t> handles;
    uint64_t lookups, refs, allocations, native_peak;
};
struct BoSpec { uint64_t handle, iova, bytes; uint32_t id, flags = 0, state = DARWIN_BO_ACTIVE; };
struct Fixture {
    const char *name;
    std::vector<BoSpec> bos;
    std::vector<tu_resource_range> ranges;
    std::vector<NativeAdrenoAbiSubmitBuffer> commands;
    uint32_t fallback = 0;
    bool legacy = false;
};
struct Device {
    std::unique_ptr<tu_device> dev = std::make_unique<tu_device>();
    std::unique_ptr<darwin_retire_state> retire = std::make_unique<darwin_retire_state>();
    explicit Device(const std::vector<BoSpec> &specs) {
        dev->darwin_retire = retire.get(); retire->device = dev.get();
        assert(pthread_mutex_init(&retire->lock,nullptr) == 0);
        std::vector<uint32_t> active;
        for (const auto &s : specs) {
            assert(s.id && s.id <= DARWIN_NATIVE_BO_LIMIT);
            dev->objects[s.id] = {s.handle,s.iova,s.bytes,s.id,s.flags,1};
            retire->nodes[s.id].bo = {s.iova,s.bytes,s.id};
            retire->nodes[s.id].state = s.state;
            if (s.state == DARWIN_BO_ACTIVE) active.push_back(s.id);
        }
        std::sort(active.begin(),active.end(),[&](uint32_t a,uint32_t b) {
            return retire->nodes[a].bo.iova < retire->nodes[b].bo.iova;
        });
        retire->active_bos.root = tree(active,0,active.size());
    }
    rb_node *tree(const std::vector<uint32_t> &ids,size_t lo,size_t hi) {
        if (lo == hi) return nullptr;
        const size_t mid = lo + (hi-lo)/2;
        rb_node *node = &retire->nodes[ids[mid]].active_iova;
        node->left = tree(ids,lo,mid); node->right = tree(ids,mid+1,hi);
        return node;
    }
    ~Device() { assert(pthread_mutex_destroy(&retire->lock) == 0); }
};
template<class T> static void add(util_dynarray *a,const std::vector<T> &values) {
    if (!values.empty()) {
        void *space=util_dynarray_grow_bytes(a,values.size(),sizeof(T)); assert(space);
        std::memcpy(space,values.data(),values.size()*sizeof(T));
    }
}
static tu_darwin_queue_submit *make_submit(const Fixture &f) {
    auto *submit=static_cast<tu_darwin_queue_submit *>(std::calloc(1,sizeof(tu_darwin_queue_submit)));
    assert(submit);
    init(&submit->commands); init(&submit->ranges); init(&submit->resources); init(&submit->native_ranges);
    add(&submit->ranges,f.ranges); add(&submit->commands,f.commands);
    submit->fallback_reasons=f.fallback;
    return submit;
}
using Collector=VkResult (*)(tu_device *,tu_darwin_queue_submit *,bool);
static Observation run(const Fixture &f,Collector collect,int fail=-1) {
    Device d(f.bos); allocation_fail_after=-1;
    auto *submit=make_submit(f);
    grows=range_lookups=references=releases=0;
    allocation_fail_after=fail;
    VkResult result=collect(d.dev.get(),submit,f.legacy);
    allocation_fail_after=-1;
    assert(pthread_mutex_trylock(&d.retire->lock) == 0);
    assert(pthread_mutex_unlock(&d.retire->lock) == 0);
    Observation o{result,submit->fallback_reasons,{},{},range_lookups,references,grows,
        util_dynarray_num_elements(&submit->native_ranges,NativeAdrenoAbiSubmitResourceV2)};
    util_dynarray_foreach(&submit->native_ranges,NativeAdrenoAbiSubmitResourceV2,r) {
        o.native.emplace_back(r->handle,r->offset,r->bytes,r->access); assert(!r->reserved);
    }
    util_dynarray_foreach(&submit->resources,darwin_submit_resource,r) {
        o.handles.push_back(r->bo->darwin_handle);
        assert(r->bo->refs==2); // Exactly one collector-owned hold per BO.
    }
    std::sort(o.handles.begin(),o.handles.end());
    assert(std::adjacent_find(o.handles.begin(),o.handles.end())==o.handles.end());
    darwin_submit_finish(d.dev.get(),submit);
    assert(references==releases);
    for (const auto &s:f.bos) assert(d.dev->objects[s.id].refs==1);
    return o;
}
static void same(const Observation &a,const Observation &b) {
    assert(a.result==b.result && a.fallback==b.fallback);
    assert(a.native==b.native && a.handles==b.handles && a.refs==b.refs);
}
static Fixture workload(unsigned distinct,unsigned repeats) {
    Fixture f{"repeated distinct ranges",{},{},{}};
    for (unsigned n=0;n<distinct;n++) {
        uint64_t start=0x10000000ULL+n*0x10000ULL;
        f.bos.push_back({0x100000000ULL+n,start,0x4000,n+1});
    }
    // Interleave repetitions as CS and descriptor-set sources do.
    for (unsigned r=0;r<repeats;r++) for (unsigned n=0;n<distinct;n++) {
        unsigned at=(n*17U+r)%distinct;
        f.ranges.push_back({f.bos[at].iova+128,1024,(at&1)?3U:1U});
    }
    return f;
}
static void semantic() {
    const std::vector<BoSpec> bos={{0x100000001ULL,0x1000,0x1000,1},
        {0x200000002ULL,0x2000,0x1000,2}, {0x300000003ULL,0x4000,0x1000,3,TU_BO_ALLOC_GPU_READ_ONLY},
        {0x400000004ULL,0x6000,0x1000,4,0,2}};
    std::vector<Fixture> cases={
        {"empty",bos,{},{}},
        {"exact duplicates",bos,{{0x1100,64,1},{0x1100,64,1},{0x1100,64,1}},{}},
        {"overlap same and different access",bos,{{0x1180,128,2},{0x1100,128,1},
            {0x1140,128,1},{0x1180,128,2},{0x1100,128,3}},{}},
        {"adjacent BOs stay separate",bos,{{0x1f00,256,1},{0x2000,256,1},{0x2000,256,1}},{}},
        {"crossing BO stays unknown",bos,{{0x1f80,256,1},{0x1f80,256,1}},{}},
        {"zero and unknown",bos,{{0,128,1},{0x1100,0,1},{0x8000,64,1},{0x8000,64,1}},{}},
        {"readonly stripping",bos,{{0x4100,64,2},{0x4100,64,3},{0x4100,64,3},{0x4180,64,1}},{}},
        {"zero access retains BO",bos,{{0x1100,64,0},{0x1100,64,0}},{}},
        {"IBs join source ranges",bos,{{0x1100,64,1}},{{0x100000001ULL,0x1100,64},{0x200000002ULL,0x2000,64}}},
        {"existing fallback",bos,{{0x1100,64,1}}, {},8,false},
        {"legacy keeps all active BOs",bos,{{0x1100,64,1}}, {},0,true},
        {"reused IOVA gem original",{{1,0x1000,0x1000,1}},{{0x1100,64,1},{0x1100,64,1}},{}},
        {"reused IOVA gem new handle",{{0x900000001ULL,0x1000,0x1000,1}},{{0x1100,64,1},{0x1100,64,1}},{}},
    };
    for (const auto &f:cases) same(run(f,before::darwin_collect_submit_resources),run(f,after::darwin_collect_submit_resources));
    auto adjacent=run(cases[3],after::darwin_collect_submit_resources);
    assert(adjacent.native==std::vector<Native>({{0x100000001ULL,0xf00,256,1},{0x200000002ULL,0,256,1}}));
    assert(adjacent.handles==std::vector<uint64_t>({0x100000001ULL,0x200000002ULL}));
    auto crossing=run(cases[4],after::darwin_collect_submit_resources);
    assert(crossing.fallback==TU_RESOURCE_FALLBACK_DEVICE_ADDRESS && crossing.native.empty());
    assert(crossing.handles.size()==3);
    auto readonly=run(cases[6],after::darwin_collect_submit_resources);
    assert(readonly.native==std::vector<Native>({{0x300000003ULL,0x100,64,1},{0x300000003ULL,0x180,64,1}}));
    auto overlap=run(cases[2],after::darwin_collect_submit_resources);
    assert(overlap.native==std::vector<Native>({{0x100000001ULL,0x100,192,1},
        {0x100000001ULL,0x180,128,2},{0x100000001ULL,0x100,128,3}}));
    const Fixture failure{"allocation cleanup",bos,{{0x1100,64,1},{0x2100,64,3},{0x8000,64,1}},
        {{0x100000001ULL,0x1100,64},{0x200000002ULL,0x2100,64}}};
    unsigned failures=0;
    for (auto collector:{before::darwin_collect_submit_resources,after::darwin_collect_submit_resources}) {
        auto complete=run(failure,collector);
        for (unsigned at=0;at<complete.allocations;at++) {
            auto failed=run(failure,collector,int(at));
            assert(failed.result==VK_ERROR_OUT_OF_HOST_MEMORY); failures++;
        }
        same(run(failure,collector),complete); // A later submission is unaffected.
    }
    for (unsigned repeat:{1U,32U,128U}) {
        auto f=workload(584,repeat);
        auto a=run(f,before::darwin_collect_submit_resources),b=run(f,after::darwin_collect_submit_resources);
        same(a,b); assert(a.lookups==584ULL*repeat && b.lookups==584);
        assert(a.native.size()==584 && b.native.size()==584);
    }
    std::printf("{\"passed\":true,\"semantic_cases\":%zu,\"failure_cleanup_cases\":%u,"
        "\"workloads\":3,\"actual_lookup\":true,\"native_ranges_equal\":true,\"references_balanced\":true}\n",cases.size(),failures);
}
static double benchmark_one(const Fixture &f,Collector collect,unsigned iterations) {
    Device d(f.bos);
    double total=0;
    for (unsigned i=0;i<iterations;i++) {
        allocation_fail_after=-1; auto *submit=make_submit(f);
        auto begin=std::chrono::steady_clock::now();
        assert(collect(d.dev.get(),submit,false)==VK_SUCCESS);
        auto end=std::chrono::steady_clock::now();
        total+=std::chrono::duration<double,std::milli>(end-begin).count();
        assert(util_dynarray_num_elements(&submit->native_ranges,NativeAdrenoAbiSubmitResourceV2)==584);
        darwin_submit_finish(d.dev.get(),submit);
    }
    return total/iterations;
}
static void benchmark() {
    std::printf("{\"unit\":\"ms\",\"scope\":\"host O2 actual collector only; fixture and cleanup excluded\",\"cases\":[");
    bool first=true;
    for (unsigned repeat:{1U,32U,128U}) {
        auto f=workload(584,repeat);
        auto a=run(f,before::darwin_collect_submit_resources),b=run(f,after::darwin_collect_submit_resources); same(a,b);
        std::vector<double> old,newer;
        for (unsigned round=0;round<5;round++) {
            if (round&1) {
                newer.push_back(benchmark_one(f,after::darwin_collect_submit_resources,12));
                old.push_back(benchmark_one(f,before::darwin_collect_submit_resources,12));
            } else {
                old.push_back(benchmark_one(f,before::darwin_collect_submit_resources,12));
                newer.push_back(benchmark_one(f,after::darwin_collect_submit_resources,12));
            }
        }
        std::sort(old.begin(),old.end()); std::sort(newer.begin(),newer.end());
        std::printf("%s{\"distinct\":584,\"repetitions\":%u,\"raw_ranges\":%zu,"
            "\"old_lookups\":%llu,\"new_lookups\":%llu,\"old_median_ms\":%.6f,"
            "\"new_median_ms\":%.6f,\"old_max_ms\":%.6f,\"new_max_ms\":%.6f,\"speedup\":%.4f}",
            first?"":",",repeat,f.ranges.size(),(unsigned long long)a.lookups,(unsigned long long)b.lookups,
            old[2],newer[2],old.back(),newer.back(),old[2]/newer[2]); first=false;
    }
    std::puts("]}");
}
int main(int argc,char **argv) {
    assert(argc==2);
    if (!std::strcmp(argv[1],"--semantic")) semantic();
    else { assert(!std::strcmp(argv[1],"--benchmark")); benchmark(); }
}
