#include <assert.h>
#include <stdio.h>
#include "../src/sensor_brightness_identity.h"

int main(void)
{
    const struct nabu_als_claim claim = {
        .virtual_id=0x8000000081ULL, .source_id=0x100000082ULL, .suid={0x11,0x22},
        .generation=7, .association_abi=1, .built_in=true, .als_usage=true
    };
    const struct nabu_als_source_identity actual = {
        .registry_id=0x100000082ULL, .suid={0x11,0x22}, .generation=7,
        .source_abi=1, .kind=3, .class_matches=true, .active=true,
        .built_in=true, .lux_units=true
    };
    const uintptr_t pc=0x1aefa570cULL;
    assert(nabu_als_identity_matches(&claim,&actual));
    assert(nabu_als_matching_target(&claim,&actual,pc,claim.virtual_id,pc)==claim.source_id);
    assert(nabu_als_matching_target(&claim,&actual,pc,claim.virtual_id+1,pc)==claim.virtual_id+1);
    assert(nabu_als_matching_target(&claim,&actual,pc,claim.virtual_id,pc+4)==claim.virtual_id);
    assert(nabu_als_matching_target(&claim,&actual,0,claim.virtual_id,0)==claim.virtual_id);
    assert(nabu_als_matching_target(NULL,&actual,pc,claim.virtual_id,pc)==claim.virtual_id);
    assert(!nabu_als_identity_matches(&claim,NULL));
    unsigned rejected=0;
    for(unsigned n=0;n<9;++n){
        struct nabu_als_claim changed=claim;
        switch(n){
        case 0:changed.virtual_id=0;break;
        case 1:changed.source_id=0;break;
        case 2:changed.source_id++;break;
        case 3:changed.generation++;break;
        case 4:changed.generation=0;break;
        case 5:changed.association_abi++;break;
        case 6:changed.suid[0]^=1;break;
        case 7:changed.built_in=false;break;
        case 8:changed.als_usage=false;break;
        }
        assert(!nabu_als_identity_matches(&changed,&actual));++rejected;
    }
    for(unsigned n=0;n<9;++n){
        struct nabu_als_source_identity changed=actual;
        switch(n){
        case 0:changed.registry_id++;break;
        case 1:changed.suid[1]++;break;
        case 2:changed.generation++;break;
        case 3:changed.source_abi++;break;
        case 4:changed.kind=0;break;
        case 5:changed.class_matches=false;break;
        case 6:changed.active=false;break;
        case 7:changed.built_in=false;break;
        case 8:changed.lux_units=false;break;
        }
        assert(nabu_als_matching_target(&claim,&changed,pc,claim.virtual_id,pc)==claim.virtual_id);
        ++rejected;
    }
    puts("PASS: real 64-bit source/SUID/generation match, exact caller and virtual ID scope, 18 stale/foreign/inactive identity refusals");
    assert(rejected==18);
}
