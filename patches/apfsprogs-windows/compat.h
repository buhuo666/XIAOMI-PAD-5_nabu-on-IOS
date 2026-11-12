// Windows regular-file adapter for the pinned apfsprogs formatter/checker.
// No raw device support. Filesystem structures and algorithms are unchanged.
#pragma once
#include <stdint.h>
#include <stddef.h>
#include <stdlib.h>
#include <stdio.h>
#include <errno.h>
#include <io.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>
#include <limits.h>
#include <sys/types.h>
typedef int64_t loff_t;
#ifndef S_IFLNK
#define S_IFLNK 0120000
#endif
#ifndef S_IFSOCK
#define S_IFSOCK 0140000
#endif
#ifndef S_IFBLK
#define S_IFBLK 0060000
#endif
// The new APFS root directory belongs to root on iPadOS, independently of
// the Windows account that runs the formatter.
static inline unsigned geteuid(void) { return 0; }
static inline unsigned getegid(void) { return 0; }
static inline int nabu_open(const char *path,int flags) {
    if(path[0]=='\\' && path[1]=='\\') { errno=EINVAL; return -1; }
    return _open(path,flags|_O_BINARY);
}
static inline ssize_t nabu_pread(int fd,void *buf,size_t size,int64_t offset) {
    if(size>INT_MAX || offset<0 || _lseeki64(fd,offset,SEEK_SET)<0) return -1;
    return _read(fd,buf,(unsigned)size);
}
static inline ssize_t nabu_pwrite(int fd,const void *buf,size_t size,int64_t offset) {
    if(size>INT_MAX || offset<0 || _lseeki64(fd,offset,SEEK_SET)<0) return -1;
    return _write(fd,buf,(unsigned)size);
}
#define open nabu_open
#define pread nabu_pread
#define pwrite nabu_pwrite
#define stat _stat64
#define fstat _fstat64
