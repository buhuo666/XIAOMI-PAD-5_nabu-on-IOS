#pragma once
#include <errno.h>
static inline int ioctl(int fd,unsigned long request,void *out)
{ (void)fd;(void)request;(void)out; errno=ENOTTY; return -1; }
