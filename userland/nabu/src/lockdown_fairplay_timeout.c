/* Give the stock 20F66 Lockdown HWInfo RPC a receive deadline. Its native
 * error handling may then finish startup when fairplayd cannot initialize.
 * No reply, identity, certificate, or authentication result is synthesized.
 */
#include <stdint.h>
#include <stddef.h>
#include <stdarg.h>

typedef struct {
    uint32_t bits, size, remote_port, local_port, voucher_port;
    int32_t id;
} nabu_mach_header;
extern int32_t mach_msg(nabu_mach_header *, uint32_t, uint32_t, uint32_t,
                        uint32_t, uint32_t, uint32_t);
extern int *__error(void);
extern int vsnprintf(char *, size_t, const char *, va_list);
extern long write(int, const void *, size_t);
extern const char *getprogname(void);
extern uint32_t _dyld_image_count(void);
extern intptr_t _dyld_get_image_vmaddr_slide(uint32_t);
extern const char *_dyld_get_image_name(uint32_t);

static int enabled;
static uintptr_t hwinfo_call_return;
enum { RECEIVE_TIMEOUT = 0x100, HWINFO_TIMEOUT_MS = 5000 };

static int equal(const char *a, const char *b)
{
    if (!a || !b) return 0;
    while (*a && *a==*b) { ++a; ++b; }
    return *a==*b;
}

static void trace(const char *format, ...)
{
    int saved=*__error();
    char text[256];
    va_list args;
    va_start(args,format);
    int n=vsnprintf(text,sizeof(text),format,args);
    va_end(args);
    if (n>0) write(2,text,(size_t)n<sizeof(text) ? (size_t)n : sizeof(text)-1);
    *__error()=saved;
}

__attribute__((constructor)) static void setup(void)
{
    int saved=*__error();
    if (equal(getprogname(),"lockdownd")) {
        for (uint32_t i=0;i<_dyld_image_count();++i) {
            if (!equal(_dyld_get_image_name(i),"/usr/libexec/lockdownd")) continue;
            hwinfo_call_return=(uintptr_t)(0x10002bdd8ULL+_dyld_get_image_vmaddr_slide(i));
            enabled=1;
            trace("NABU LOCKDOWN TIMEOUT: original HWInfo RPC receive deadline=%u ms enabled\n",HWINFO_TIMEOUT_MS);
            break;
        }
    }
    *__error()=saved;
}

static int32_t call_with_deadline(nabu_mach_header *message, uint32_t options,
    uint32_t send_size, uint32_t receive_size, uint32_t receive_name,
    uint32_t timeout, uint32_t notify, uintptr_t caller)
{
    const int selected=enabled && caller==hwinfo_call_return && message &&
        message->id==1203 && options==3 && send_size==24 && receive_size==60 && timeout==0;
    if (selected) {
        options|=RECEIVE_TIMEOUT;
        timeout=HWINFO_TIMEOUT_MS;
        trace("NABU LOCKDOWN TIMEOUT: HWInfo request sent with bounded receive\n");
    }
    int32_t result=mach_msg(message,options,send_size,receive_size,receive_name,timeout,notify);
    if (selected)
        trace("NABU LOCKDOWN TIMEOUT: original mach_msg result=%#x\n",(uint32_t)result);
    return result;
}

static int32_t bounded_mach_msg(nabu_mach_header *message, uint32_t options,
    uint32_t send_size, uint32_t receive_size, uint32_t receive_name,
    uint32_t timeout, uint32_t notify)
{
    return call_with_deadline(message,options,send_size,receive_size,receive_name,
        timeout,notify,(uintptr_t)__builtin_return_address(0));
}

__attribute__((used,section("__DATA,__interpose")))
static const struct { const void *replacement, *original; } interposer = {
    (const void *)&bounded_mach_msg, (const void *)&mach_msg
};
