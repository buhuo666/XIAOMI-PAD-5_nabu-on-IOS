// SPDX-License-Identifier: BSD-2-Clause-Patent
#include <IOKit/IOLib.h>
#include "NabuWlfw.h"
#include "NabuWirelessLog.h"
extern "C" bool nabu_assign_memory(uint64_t,uint64_t,const uint32_t*,unsigned,const uint32_t*,unsigned);
static NabuWlfw::Region assigned[2];
static unsigned assigned_count;

extern "C" bool nabu_msa_prepare(const NabuWlfw::Region *regions,unsigned count) {
    const uint32_t hlos=3,owners[]={15,24,25};
    // Match the ath10k sequence: firmware finishes its MSA response before XPU changes.
    IOSleep(20);
    for(unsigned i=0;i<count;++i){
        unsigned destinations=regions[i].secure?2:3;
        nabu_wireless_log("NABU MSA: grant region=%u address=%#llx size=%#x secure=%u\n",i,regions[i].address,regions[i].size,regions[i].secure);
        if(!nabu_assign_memory(regions[i].address,regions[i].size,&hlos,1,owners,destinations))return false;
        assigned[assigned_count++]=regions[i];
    }
    return count!=0;
}
extern "C" void nabu_msa_finish() {
    const uint32_t hlos=3,owners[]={15,24,25};
    while(assigned_count){
        auto &region=assigned[assigned_count-1];
        bool ok=nabu_assign_memory(region.address,region.size,owners,region.secure?2:3,&hlos,1);
        nabu_wireless_log("NABU MSA: reclaim address=%#llx result=%u\n",region.address,ok);
        if(!ok)return;
        --assigned_count;
    }
}
