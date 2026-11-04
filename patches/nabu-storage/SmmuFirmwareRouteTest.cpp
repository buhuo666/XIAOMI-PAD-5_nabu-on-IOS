// SPDX-License-Identifier: BSD-2-Clause-Patent
#include <array>
#include <cstdint>
#include <cassert>
#include <cstdio>
#include <vector>
#include <utility>
#include "headers/SmmuTakeover.h"

int main()
{
  std::array<uint32_t,0x100000/4> r{};
  std::vector<std::pair<unsigned,uint32_t>> writes;
  unsigned drop=~0U;
  auto reset=[&] {
    r.fill(0); writes.clear(); drop=~0U;
    r[0x20/4]=0x40000080; // synthetic IDR0; not present in the run10 photograph
    r[0x24/4]=0x60000038; r[0x28/4]=0x5555; // photographed IDR1/IDR2
    r[(0x800+4*2)/4]=0x80000300; r[(0xc00+4*2)/4]=1;
    // Old context is translating and shared by an unrelated device. Leave it intact.
    r[(0x800+4*3)/4]=0x80000301; r[(0xc00+4*3)/4]=1;
    r[(128+1)*4096/4]=1; r[(0x1000+4)/4]=0x12340000;
    r[(0x1800+4)/4]=0x20001; r[((128+1)*4096+0x20)/4]=0xdeadbeef;
  };
  auto read=[&](unsigned at) { return r.at(at/4); };
  auto plan=[&](bool allow=true) { return planUfsSmmu(0x300,0x183524000ULL,0x22000,read,0x100000,allow); };
  UfsSmmuPlan p;
  auto write=[&](unsigned at,uint32_t value) {
    // Only the fresh context and this SID's S2CR may be changed.
    assert(at==(p.pages+p.bank)*4096 || at==0x1800+4*p.bank ||
           at==0x1000+4*p.bank || at==0xc00+4*2);
    if (at==0xc00+4*2) {
      assert(read((p.pages+p.bank)*4096)==0);
      assert(read(0x1800+4*p.bank)==1 && read(0x1000+4*p.bank)==0x10000);
    }
    writes.emplace_back(at,value);
    if (at!=drop) r.at(at/4)=value;
  };
  auto configure=[&] { return configureUfsSmmu(p,0x300,read,write); };
  reset(); assert(plan(false).error); p=plan();
  assert(!p.error && p.retarget && !p.reuse && p.slot==2 && p.bank==55);
  auto before=r;
  assert(!configure()); assert(writes.size()==4);
  assert(read(0x800+4*2)==0x80000300 && read(0xc00+4*2)==55);
  for (unsigned i=0;i<r.size();i++) {
    unsigned at=i*4;
    if (at!=(128+55)*4096 && at!=0x1800+4*55 && at!=0x1000+4*55 && at!=0xc00+4*2)
      assert(r[i]==before[i]);
  }
  p=plan();writes.clear();assert(p.reuse&&!p.retarget&&!configure()&&writes.empty());
  // An already-used destination is skipped, without changing that user's context.
  reset();r[(0x800+4*4)/4]=0x80000400;r[(0xc00+4*4)/4]=55;
  p=plan();assert(!p.error&&p.bank==54&&p.retarget);
  // Duplicate matches, masks, unsupported attributes and invalid source banks remain forbidden.
  reset();r[(0x800+4*4)/4]=0x80000300;r[(0xc00+4*4)/4]=2;assert(plan().error);
  reset();r[(0x800+4*2)/4]=0x80010300;assert(plan().error);
  reset();r[(0xc00+4*2)/4]=0x01000001;assert(plan().error);
  reset();r[(0xc00+4*2)/4]=56;assert(plan().error);
  // Stale plans are rejected before changing anything.
  reset();p=plan();r[(0xc00+4*2)/4]=2;assert(configure()&&writes.empty());
  reset();p=plan();r[(0x800+4*2)/4]=0x80000302;assert(configure()&&writes.empty());
  reset();p=plan();r[(0x800+4*4)/4]=0x80000400;r[(0xc00+4*4)/4]=p.bank;
  assert(configure()&&writes.empty());
  reset();p=plan();r[(128+p.bank)*4096/4]=1;assert(configure()&&writes.empty());
  reset();r[0x20/4]=0x40000081;assert(plan().error);
  // A blocked context write cannot redirect the live SID; a blocked redirect leaves its old route.
  for (unsigned at:{0x1800+4*55,0x1000+4*55,0xc00+4*2}) {
    reset();p=plan();drop=at;assert(configure());assert(read(0xc00+4*2)==1);
  }
  puts("PASS: run10 exact-SID retarget, old/shared context preservation, unused-bank selection, stale plan and blocked-write guards");
}
