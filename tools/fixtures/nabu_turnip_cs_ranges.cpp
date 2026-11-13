// Appended to the production collector adapter by check_nabu_turnip_cs_ranges.py.
#include <map>

/* RECORDING_PRELUDE */

using RangeKey=std::pair<uint64_t,uint64_t>;
static std::map<RangeKey,uint32_t> range_access(const std::vector<tu_resource_range> &ranges) {
    std::map<RangeKey,uint32_t> result;
    for(const auto &r:ranges)if(r.iova && r.size)result[{r.iova,r.size}]|=r.access;
    return result;
}
struct Recorded {
    Fixture fixture;
    VkResult status;
    uint64_t allocations,source_count,forwarded_count;
    double milliseconds;
};
static void recording_finish(tu_cs &cs) {
    tu_resource_range_index_finish(&cs.resource_range_index);
    util_dynarray_fini(&cs.resource_ranges);
}
static Recorded record_fixture(const Fixture &input,bool indexed,unsigned fanout=3,int fail=-1) {
    tu_cs source{},forwarded{};tu_cmd_buffer command{};
    init(&source.resource_ranges);init(&forwarded.resource_ranges);init(&command.resource_ranges);
    source.mode=forwarded.mode=TU_CS_MODE_GROW;
    grows=0;allocation_fail_after=fail;
    auto begin=std::chrono::steady_clock::now();
    for(const auto &r:input.ranges) {
        if(indexed)record_after::tu_cs_use_range(&source,r.iova,r.size,r.access);
        else record_before::tu_cs_use_range(&source,r.iova,r.size,r.access);
    }
    for(unsigned i=0;i<fanout;i++) {
        if(indexed)record_after::tu_cs_use_resources(&forwarded,&source);
        else record_before::tu_cs_use_resources(&forwarded,&source);
    }
    util_dynarray_foreach(&forwarded.resource_ranges,tu_resource_range,r) {
        if(indexed)record_after::tu_cmd_use_range(&command,*r);
        else record_before::tu_cmd_use_range(&command,*r);
    }
    auto end=std::chrono::steady_clock::now();
    VkResult status=source.record_result!=VK_SUCCESS?source.record_result:
        forwarded.record_result!=VK_SUCCESS?forwarded.record_result:command.vk.error;
    Recorded result{input,status,grows,
        util_dynarray_num_elements(&source.resource_ranges,tu_resource_range),
        util_dynarray_num_elements(&forwarded.resource_ranges,tu_resource_range),
        std::chrono::duration<double,std::milli>(end-begin).count()};
    result.fixture.ranges.clear();
    util_dynarray_foreach(&command.resource_ranges,tu_resource_range,r)result.fixture.ranges.push_back(*r);
    allocation_fail_after=-1;
    recording_finish(source);recording_finish(forwarded);
    util_dynarray_fini(&command.resource_ranges);
    assert(scratch_live==0);
    return result;
}
static void same_effective_native(const Observation &a,const Observation &b) {
    assert(a.result==b.result && a.fallback==b.fallback && a.handles==b.handles && a.refs==b.refs);
    std::map<uint64_t,std::vector<uint64_t>> boundaries;
    for(const auto *ranges:{&a.native,&b.native})for(const auto &r:*ranges) {
        auto &cuts=boundaries[std::get<0>(r)];cuts.push_back(std::get<1>(r));
        cuts.push_back(std::get<1>(r)+std::get<2>(r));
    }
    for(auto &entry:boundaries) {
        const auto handle=entry.first;
        auto &cuts=entry.second;
        std::sort(cuts.begin(),cuts.end());cuts.erase(std::unique(cuts.begin(),cuts.end()),cuts.end());
        for(size_t i=1;i<cuts.size();i++) {
            auto access=[&](const Observation &o) {
                uint32_t mask=0;
                for(const auto &r:o.native)if(std::get<0>(r)==handle && std::get<1>(r)<=cuts[i-1]
                    && cuts[i]<=std::get<1>(r)+std::get<2>(r))mask|=std::get<3>(r);
                return mask;
            };
            assert(access(a)==access(b));
        }
    }
}
static void check_recording(const Fixture &f) {
    auto old=record_fixture(f,false),newer=record_fixture(f,true);
    assert(old.status==VK_SUCCESS && newer.status==VK_SUCCESS);
    assert(range_access(old.fixture.ranges)==range_access(newer.fixture.ranges));
    assert(range_access(newer.fixture.ranges)==range_access(f.ranges));
    same_effective_native(run(old.fixture,after::darwin_collect_submit_resources),
                          run(newer.fixture,after::darwin_collect_submit_resources));
}
static void recording_semantic() {
    const std::vector<BoSpec> bos={{0x100000001ULL,0x1000,0x1000,1},
        {0x200000002ULL,0x2000,0x1000,2},{0x300000003ULL,0x4000,0x1000,3,TU_BO_ALLOC_GPU_READ_ONLY}};
    std::vector<Fixture> cases={
        {"empty",bos,{},{}},
        {"access union",bos,{{0x1100,64,1},{0x1100,64,2},{0x1100,64,0}},{}},
        {"different sizes, overlaps and adjacent BOs",bos,{{0x1100,64,1},{0x1100,128,2},
            {0x1140,64,3},{0x1f00,256,1},{0x2000,256,2}},{}},
        {"readonly and unknown",bos,{{0x4100,64,2},{0x4100,64,1},{0x8000,64,1},{0x8000,64,2}},{}},
        {"invalid zero",bos,{{0,64,1},{0x1100,0,1},{0x1100,64,0}},{}},
        {"crossing BO, IB and fallback",bos,{{0x1f80,256,1},{0x1f80,256,2}},{{0x100000001ULL,0x1100,64}},8},
        {"legacy",bos,{{0x1100,64,1},{0x1100,64,2}},{},0,true},
    };
    uint32_t random=0x52414e47;
    for(unsigned iteration=0;iteration<24;iteration++) {
        Fixture f{"random repeated access",bos,{},{}};
        for(unsigned i=0;i<160;i++) {
            random=random*1664525U+1013904223U;
            tu_resource_range r{0x1000+(random&0x7fc0),16+((random>>16)&0x7f),(random>>24)&3};
            f.ranges.push_back(r);if(random&1)f.ranges.push_back(r);
        }
        cases.push_back(f);
    }
    for(unsigned repetitions:{1U,32U,128U})cases.push_back(workload(584,repetitions));
    Fixture collisions{"range index collisions",{{7,0x100000,0x100000,1}},{},{}};
    for(uint64_t offset=0;collisions.ranges.size()<40;offset+=8)
        if((tu_resource_range_hash(0x100000+offset,8)&127)==0) {
            assert(offset+8<=0x100000);collisions.ranges.push_back({0x100000+offset,8,1});
        }
    for(unsigned i=0;i<40;i++)collisions.ranges.push_back({collisions.ranges[i].iova,8,2});
    cases.push_back(collisions);
    for(const auto &f:cases)check_recording(f);

    // Child streams append to the owner; external standalone streams do not
    // own or retain an index. Reset starts a new permission epoch.
    tu_cs owner{},child{},external{};owner.mode=TU_CS_MODE_GROW;
    child.mode=external.mode=TU_CS_MODE_EXTERNAL;child.parent=&owner;
    init(&owner.resource_ranges);init(&child.resource_ranges);init(&external.resource_ranges);
    record_after::tu_cs_use_range(&child,0x1000,64,1);
    assert(owner.resource_ranges.size==sizeof(tu_resource_range) && !child.resource_ranges.size);
    assert(!child.resource_range_index.slots);
    record_after::tu_cs_use_resources(&owner,&owner);
    record_after::tu_cs_use_range(&external,0x2000,64,1);
    assert(!external.resource_ranges.size && !external.resource_range_index.slots);
    util_dynarray_clear(&owner.resource_ranges);tu_resource_range_index_clear(&owner.resource_range_index);
    record_after::tu_cs_use_range(&child,0x1000,64,2);
    assert(static_cast<tu_resource_range *>(owner.resource_ranges.data)[0].access==2);
    allocation_fail_after=0;record_after::tu_cs_use_range(&child,0x1000,64,1);
    assert(owner.record_result==VK_SUCCESS && static_cast<tu_resource_range *>(owner.resource_ranges.data)[0].access==3);
    allocation_fail_after=-1;
    recording_finish(owner);recording_finish(child);recording_finish(external);
    assert(scratch_live==0);

    auto failure=workload(130,2);unsigned failed=0;
    for(bool indexed:{false,true}) {
        auto full=record_fixture(failure,indexed);
        for(unsigned i=0;i<full.allocations;i++) {
            auto broken=record_fixture(failure,indexed,3,int(i));
            assert(broken.status==VK_ERROR_OUT_OF_HOST_MEMORY);failed++;
        }
        assert(record_fixture(failure,indexed).status==VK_SUCCESS);
    }
    std::printf("{\"passed\":true,\"semantic_cases\":%zu,\"allocation_failures\":%u,"
        "\"collision_pairs\":40,\"parent_external_self\":true,\"reset_permissions\":true,"
        "\"same_effective_native_permissions\":true,\"actual_bo_lookup_and_holds\":true,\"balanced_cleanup\":true}\n",cases.size(),failed);
}
static void recording_benchmark() {
    std::printf("{\"unit\":\"ms\",\"scope\":\"actual CS record, 3 stream copies and command record; host O2\",\"cases\":[");
    bool first=true;
    for(unsigned repeats:{1U,32U,128U}) {
        auto f=workload(584,repeats);std::vector<double> old,newer;
        uint64_t old_count=0,new_count=0,old_source=0,new_source=0;
        for(unsigned round=0;round<7;round++) {
            auto a=record_fixture(f,false),b=record_fixture(f,true);
            assert(a.status==VK_SUCCESS && b.status==VK_SUCCESS);
            assert(range_access(a.fixture.ranges)==range_access(b.fixture.ranges));
            old.push_back(a.milliseconds);newer.push_back(b.milliseconds);
            old_count=a.forwarded_count;new_count=b.forwarded_count;
            old_source=a.source_count;new_source=b.source_count;
        }
        std::sort(old.begin(),old.end());std::sort(newer.begin(),newer.end());
        std::printf("%s{\"repetitions\":%u,\"source_before\":%llu,\"source_after\":%llu,"
            "\"forwarded_before\":%llu,\"forwarded_after\":%llu,\"old_median_ms\":%.6f,\"new_median_ms\":%.6f,\"speedup\":%.4f}",
            first?"":",",repeats,(unsigned long long)old_source,(unsigned long long)new_source,
            (unsigned long long)old_count,(unsigned long long)new_count,old[3],newer[3],old[3]/newer[3]);first=false;
    }
    std::puts("]}");
}
int main(int argc,char **argv) {
    assert(argc==2);
    if(!std::strcmp(argv[1],"--semantic"))recording_semantic();
    else {assert(!std::strcmp(argv[1],"--benchmark"));recording_benchmark();}
}
