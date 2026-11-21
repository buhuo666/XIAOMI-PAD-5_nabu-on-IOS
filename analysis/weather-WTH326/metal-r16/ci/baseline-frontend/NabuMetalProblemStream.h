// SPDX-License-Identifier: MIT
// The published GPU service's connection-free 0x6d marker text protocol.
// 0x6d80 reserves a separate kernel budget for exception name/reason/frames.
#pragma once
#include <algorithm>
#include <cerrno>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <mutex>

namespace nabumetalproblem {
class Stream {
    std::mutex lock_;
    uint32_t sequence_=0;
public:
    template<class Marker> void send(Marker &&marker,const char *text,bool exception=false) {
        const int saved=errno;
        std::lock_guard<std::mutex> lock(lock_);
        // A complete exception contains the original helper's 96-character
        // reason and up to 20 frames. This limit also bounds ordinary errors.
        constexpr size_t limit=1024,payload=44;
        const size_t length=strnlen(text,limit);
        const unsigned parts=unsigned(std::max(size_t(1),(length+payload-1)/payload));
        const bool truncated=length==limit && text[length]!=0;
        const uint32_t sequence=++sequence_;
        for(unsigned part=0;part<parts;++part) {
            char line[64];
            const int prefix=snprintf(line,sizeof(line),"%c%08x %02u/%02u%c",
                exception?'E':'P',sequence,part+1,parts,truncated?'+':' ');
            const size_t offset=size_t(part)*payload;
            const size_t bytes=std::min(payload,length-offset);
            for(size_t i=0;i<bytes;++i) {
                const unsigned char ch=static_cast<unsigned char>(text[offset+i]);
                line[size_t(prefix)+i]=ch>=32 && ch<127?char(ch):'?';
            }
            const size_t count=size_t(prefix)+bytes;
            line[count]=0;
            marker(exception?0x6d80u:0x6d00u);
            for(size_t i=0;i<count;++i)marker(0x6d00u|static_cast<unsigned char>(line[i]));
            marker(0x6dffu);
        }
        errno=saved;
    }
};
} // namespace nabumetalproblem
