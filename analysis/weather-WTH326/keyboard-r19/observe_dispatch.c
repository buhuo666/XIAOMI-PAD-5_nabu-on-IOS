/* Count actual keyboard enqueue calls during DYLD_INSERT_LIBRARIES startup. */
#include <dispatch/dispatch.h>
#include <dlfcn.h>
#include <stdatomic.h>
#include <string.h>
static atomic_uint enqueues;
unsigned nabu_test_keyboard_enqueues(void) {return atomic_load(&enqueues);}
static void observed_async(dispatch_queue_t queue,void *context,dispatch_function_t function) {
    Dl_info info;
    if(dladdr((const void *)function,&info) && info.dli_fname &&
       strstr(info.dli_fname,"libnabu.keyboard.")) atomic_fetch_add(&enqueues,1);
    dispatch_async_f(queue,context,function);
}
__attribute__((used,section("__DATA,__interpose")))
static const struct {const void *replacement,*original;} interpose={
    (const void *)observed_async,(const void *)dispatch_async_f};
