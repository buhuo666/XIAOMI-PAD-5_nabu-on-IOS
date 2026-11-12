#pragma once
#include <stdint.h>
#include <stdlib.h>
#include <errno.h>
#define PROT_READ 1
#define PROT_WRITE 2
#define MAP_PRIVATE 2
#define MAP_FAILED ((void *)-1)
// apfsck uses private mappings, including private scratch modification. Copy
// reads provide those semantics without changing any bytes of the image.
static inline void *mmap(void *address,size_t length,int prot,int flags,int fd,int64_t offset) {
    if(address || flags!=MAP_PRIVATE || (prot&~(PROT_READ|PROT_WRITE))) {errno=EINVAL;return MAP_FAILED;}
    void *p=malloc(length);
    if(!p)return MAP_FAILED;
    size_t done=0;
    while(done<length) {
        size_t take=length-done>0x1000000?0x1000000:length-done;
        ssize_t got=nabu_pread(fd,(char *)p+done,take,offset+(int64_t)done);
        if(got<=0){free(p);return MAP_FAILED;}
        done+=(size_t)got;
    }
    return p;
}
static inline int munmap(void *p,size_t length){(void)length;free(p);return 0;}
