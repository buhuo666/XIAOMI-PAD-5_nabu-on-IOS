#include <algorithm>
#include <atomic>
#include <cassert>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <set>
#include <thread>
#include <vector>

static thread_local int fail_after=-1;
static thread_local uint64_t allocations=0;
static std::atomic<int64_t> live{0};
static bool permit(){allocations++;if(fail_after==0)return false;if(fail_after>0)fail_after--;return true;}
static void *test_calloc(size_t n,size_t s){if(!permit())return nullptr;void*p=std::calloc(n,s);if(p)live++;return p;}
static void test_free(void*p){if(p){live--;std::free(p);}}
struct util_dynarray {void*data=nullptr;size_t size=0,capacity=0;};
static void *array_grow(util_dynarray*a,size_t bytes){
    const size_t start=a->size;
    if(start+bytes>a->capacity){
        if(!permit())return nullptr;
        size_t capacity=std::max(start+bytes,a->capacity?2*a->capacity:64);
        const bool had=a->data!=nullptr;
        void*p=std::realloc(a->data,capacity);if(!p)return nullptr;
        if(!had)live++;a->data=p;a->capacity=capacity;
    }
    a->size+=bytes;return static_cast<char*>(a->data)+start;
}
#define util_dynarray_num_elements(a,T) ((a)->size/sizeof(T))
#define util_dynarray_grow(a,T,n) array_grow((a),sizeof(T)*(n))
#define util_dynarray_foreach(a,T,it) for(T*it=static_cast<T*>((a)->data); (a)->size && it < static_cast<T*>((a)->data)+(a)->size/sizeof(T); ++it)
struct tu_resource_range {uint64_t iova,size;uint32_t access;};
constexpr int TU_CS_MODE_GROW=0,TU_CS_MODE_EXTERNAL=1,VK_SUCCESS=0,VK_ERROR_OUT_OF_HOST_MEMORY=-1;
#define TU_HAS_DARWIN 1
#define calloc test_calloc
#define free test_free
namespace baseline {
#include "baseline.inc"
}
namespace candidate {
#include "candidate.inc"
}
#undef calloc
#undef free

struct Old {
    using CS=baseline::tu_cs;
    static void add(CS*c,uint64_t a,uint64_t n,uint32_t m){baseline::tu_cs_use_range(c,a,n,m);}
    static void import(CS*d,const CS*s){baseline::tu_cs_use_resources(d,s);}
    static void clear(CS*c){c->resource_ranges.size=0;baseline::tu_resource_range_index_clear(&c->resource_range_index);c->record_result=0;}
    static void finish(CS*c){baseline::tu_resource_range_index_finish(&c->resource_range_index);test_free(c->resource_ranges.data);*c={};}
    static uint64_t &visits(){return baseline::visits;}
};
struct New {
    using CS=candidate::tu_cs;
    static void add(CS*c,uint64_t a,uint64_t n,uint32_t m){candidate::tu_cs_use_range(c,a,n,m);}
    static void import(CS*d,const CS*s){candidate::tu_cs_use_resources(d,s);}
    static void clear(CS*c){c->resource_ranges.size=0;candidate::tu_resource_range_index_clear(&c->resource_range_index);c->record_result=0;}
    static void finish(CS*c){candidate::tu_resource_range_index_finish(&c->resource_range_index);test_free(c->resource_ranges.data);*c={};}
    static uint64_t &visits(){return candidate::visits;}
};
struct Pair {
    Old::CS a{};New::CS b{};
    ~Pair(){Old::finish(&a);New::finish(&b);}
    void add(uint64_t x,uint64_t n,uint32_t m){Old::add(&a,x,n,m);New::add(&b,x,n,m);same();}
    void take(Pair&s){Old::import(&a,&s.a);New::import(&b,&s.b);same();}
    void clear(){Old::clear(&a);New::clear(&b);same();}
    void recycle(){Old::finish(&a);New::finish(&b);same();}
    void same()const{
        assert(a.record_result==b.record_result && a.resource_ranges.size==b.resource_ranges.size);
        auto x=static_cast<tu_resource_range*>(a.resource_ranges.data),y=static_cast<tu_resource_range*>(b.resource_ranges.data);
        for(size_t i=0;i<a.resource_ranges.size/sizeof(*x);i++)assert(x[i].iova==y[i].iova && x[i].size==y[i].size && x[i].access==y[i].access);
    }
};
static void fill(Pair&p,unsigned n,uint64_t offset=0,uint32_t access=1){for(unsigned i=0;i<n;i++)p.add(0x10000+offset+i*64,64,access);}
static uint64_t steps=0;
static void semantic(){
    {
        Pair source,dest,chain;fill(source,584);dest.take(source);
        auto visits=New::visits();for(int i=0;i<128;i++)dest.take(source);
        assert(New::visits()==visits);steps+=129;
        // A no-op addition does not invalidate; permission expansion must.
        auto revision=source.b.resource_range_index.revision;source.add(0x10000,64,1);
        assert(source.b.resource_range_index.revision==revision);visits=New::visits();dest.take(source);assert(New::visits()==visits);
        source.add(0x10000,64,2);visits=New::visits();dest.take(source);assert(New::visits()==visits+584);steps+=3;
        source.add(0x10000,128,2);dest.take(source);steps++;
        chain.take(dest);source.add(0x300000,64,3);dest.take(source);chain.take(dest);steps+=3;
        dest.clear();dest.take(source);steps++;
        auto id=source.b.resource_range_index.identity;source.clear();fill(source,584,0x500000,2);
        assert(source.b.resource_range_index.identity!=id);dest.take(source);steps++;
        id=source.b.resource_range_index.identity;source.recycle();fill(source,584,0x600000,1);
        assert(source.b.resource_range_index.identity!=id);dest.take(source);steps++;
        // Destination growth/rehash must preserve the already imported memo.
        for(unsigned i=0;i<3000;i++)dest.add(0x900000+i*64,64,1);
        visits=New::visits();dest.take(source);assert(New::visits()==visits);steps++;
        source.b.resource_range_index.revision=UINT64_MAX;id=source.b.resource_range_index.identity;
        source.add(0xa00000,64,3);assert(source.b.resource_range_index.identity!=id && source.b.resource_range_index.revision==1);
        dest.take(source);steps++;
    }
    for(unsigned n:{0U,1U,15U,16U,17U,32U}){
        Pair s,d;fill(s,n);d.take(s);auto v=New::visits();d.take(s);
        assert(New::visits()-v==(n<16?n:0));steps+=2;
    }
    {
        Pair sources[12],d;
        for(unsigned j=0;j<12;j++){fill(sources[j],20,j*0x10000);d.take(sources[j]);}
        assert(d.b.resource_range_index.imported_count==8);
        auto v=New::visits();d.take(sources[0]);assert(New::visits()==v+20);steps+=13;
        Pair child,external;child.a.mode=child.b.mode=TU_CS_MODE_EXTERNAL;
        child.a.parent=&d.a;child.b.parent=&d.b;child.take(sources[1]);d.same();
        external.a.mode=external.b.mode=TU_CS_MODE_EXTERNAL;external.take(sources[0]);assert(!external.b.resource_ranges.size);
        d.take(d);steps+=3;
        d.a.record_result=d.b.record_result=VK_ERROR_OUT_OF_HOST_MEMORY;
        v=New::visits();d.take(sources[2]);assert(New::visits()==v);steps++;
    }
    // Identical traces over different owners, source reset/reuse, permission
    // changes, eviction and transitive imports. Compare actual recorded order.
    {
        Pair streams[16];uint32_t random=0x376369;
        for(unsigned j=0;j<16;j++)fill(streams[j],20,j*0x10000);
        for(unsigned i=0;i<12000;i++){
            random=random*1664525U+1013904223U;unsigned a=(random>>8)%16,b=(random>>16)%16;
            switch(random%12){
                case 0:streams[a].clear();break;
                case 1:streams[a].recycle();break;
                case 2:case 3:case 4:streams[a].add(0x1000+((random>>3)&511)*64,16+((random>>20)&127),(random>>29)&3);break;
                default:streams[a].take(streams[b]);break;
            }
            for(auto &s:streams)s.same();steps++;
        }
    }
    // Failure during a partial import must never create a successful memo.
    unsigned failure_cases=0;
    {
        Pair source;fill(source,130);
        New::CS full{};allocations=0;New::import(&full,&source.b);auto count=allocations;New::finish(&full);
        for(unsigned i=0;i<count;i++){
            New::CS d{};fail_after=int(i);New::import(&d,&source.b);fail_after=-1;
            assert(d.record_result==VK_ERROR_OUT_OF_HOST_MEMORY && !d.resource_range_index.imported_count);
            New::clear(&d);New::import(&d,&source.b);assert(d.record_result==VK_SUCCESS);
            assert(d.resource_ranges.size==source.b.resource_ranges.size);New::finish(&d);failure_cases++;
        }
    }
    // CS objects remain separately synchronized; identity allocation is shared.
    std::vector<std::vector<uint64_t>> ids(8);std::vector<std::thread> threads;
    for(unsigned t=0;t<8;t++)threads.emplace_back([&,t]{for(unsigned i=0;i<1000;i++){
        New::CS s{};New::add(&s,0x10000,64,1);ids[t].push_back(s.resource_range_index.identity);New::finish(&s);
    }});
    for(auto&t:threads)t.join();std::set<uint64_t> all;for(auto&v:ids)for(auto id:v)assert(id && all.insert(id).second);
    assert(live==0);
    std::printf("{\"passed\":true,\"differential_steps\":%llu,\"failure_cases\":%u,\"threads\":8,\"unique_identities\":%zu,\"live_allocations\":0,\"identity_revision_reset_eviction_parent_self_failure_rehash\":true}\n",(unsigned long long)steps,failure_cases,all.size());
}
template<class P> static std::pair<double,uint64_t> bench(unsigned n,unsigned copies,bool mutate){
    typename P::CS s{},d{};P::visits()=0;
    auto start=std::chrono::steady_clock::now();
    for(unsigned i=0;i<n;i++)P::add(&s,0x10000+i*64,64,1);
    for(unsigned i=0;i<copies;i++){
        if(mutate)P::add(&s,0x200000+i*64,64,2);
        P::import(&d,&s);
    }
    double ms=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-start).count();
    auto visits=P::visits();P::finish(&s);P::finish(&d);return {ms,visits};
}
static void benchmark(){
    std::printf("{\"scope\":\"host actual record and import, source creation included; no UI claim\",\"cases\":[");bool first=true;
    for(unsigned n:{15U,16U,128U,584U})for(unsigned copies:{1U,3U,32U,128U})for(bool mutation:{false,true}){
        std::vector<double> a,b;uint64_t av=0,bv=0;
        for(unsigned j=0;j<21;j++){auto x=bench<Old>(n,copies,mutation),y=bench<New>(n,copies,mutation);a.push_back(x.first);b.push_back(y.first);av=x.second;bv=y.second;}
        std::sort(a.begin(),a.end());std::sort(b.begin(),b.end());
        std::printf("%s{\"ranges\":%u,\"imports\":%u,\"mutating\":%s,\"old_visits\":%llu,\"new_visits\":%llu,\"old_ms\":%.6f,\"new_ms\":%.6f}",first?"":",",n,copies,mutation?"true":"false",(unsigned long long)av,(unsigned long long)bv,a[10],b[10]);first=false;
    }
    assert(live==0);std::puts("]}");
}
int main(int argc,char**argv){assert(argc==2);if(!std::strcmp(argv[1],"semantic"))semantic();else benchmark();}
