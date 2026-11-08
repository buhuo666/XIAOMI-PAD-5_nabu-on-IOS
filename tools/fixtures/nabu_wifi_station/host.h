#ifndef NABU_WIFI_STATION_HOST_H
#define NABU_WIFI_STATION_HOST_H
#include <assert.h>
#include <errno.h>
#include <pthread.h>
#include <sched.h>
#include <stdatomic.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <time.h>

#define __unused __attribute__((unused))
#define KERNEL 1
#define Z_WAITOK 1
#define Z_ZERO 2
#define LCK_SLEEP_DEFAULT 0
#define THREAD_UNINT 0
#define KERN_SUCCESS 0
typedef int wait_result_t;
typedef void *event_t;
typedef pthread_t thread_t;
typedef struct { pthread_mutex_t mutex; } lck_mtx_t;
#define LCK_GRP_DECLARE(name, label) int name __attribute__((unused))
#define LCK_MTX_DECLARE(name, group) lck_mtx_t name = { PTHREAD_MUTEX_INITIALIZER }
static pthread_mutex_t scheduler_mutex = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t scheduler_cond = PTHREAD_COND_INITIALIZER;
static unsigned scheduler_generation;
static atomic_bool finish_worker;
static pthread_t worker_thread;
static bool worker_created;
static atomic_uint drain_waits;
static atomic_uint mutation_waits;
static _Thread_local bool is_worker, is_detacher, is_mutator, is_sampler;

static void lck_mtx_lock(lck_mtx_t *lock) {
    int result = pthread_mutex_trylock(&lock->mutex);
    if (!result) return;
    assert(result == EBUSY);
    if (is_mutator) atomic_fetch_add(&mutation_waits, 1);
    assert(!pthread_mutex_lock(&lock->mutex));
}
static void lck_mtx_unlock(lck_mtx_t *lock) { assert(!pthread_mutex_unlock(&lock->mutex)); }
static void lck_mtx_sleep(lck_mtx_t *lock, int flags, event_t event, int interruptible)
{
    (void)flags; (void)event; (void)interruptible;
    assert(!pthread_mutex_lock(&scheduler_mutex));
    unsigned generation = scheduler_generation;
    if (is_detacher) atomic_fetch_add(&drain_waits, 1);
    lck_mtx_unlock(lock);
    while (generation == scheduler_generation && !(is_worker && atomic_load(&finish_worker)))
        assert(!pthread_cond_wait(&scheduler_cond, &scheduler_mutex));
    bool finish = is_worker && atomic_load(&finish_worker);
    assert(!pthread_mutex_unlock(&scheduler_mutex));
    if (finish) pthread_exit(NULL);
    lck_mtx_lock(lock);
}
static void thread_wakeup(event_t event)
{
    (void)event;
    assert(!pthread_mutex_lock(&scheduler_mutex));
    ++scheduler_generation;
    assert(!pthread_cond_broadcast(&scheduler_cond));
    assert(!pthread_mutex_unlock(&scheduler_mutex));
}
struct thread_launch { void (*run)(void *, wait_result_t); void *arg; };
static void *worker_launch(void *opaque)
{
    struct thread_launch launch = *(struct thread_launch *)opaque;
    free(opaque); is_worker = true; launch.run(launch.arg, 0); return NULL;
}
static int kernel_thread_start(void (*run)(void *, wait_result_t), void *arg, thread_t *thread)
{
    assert(!worker_created);
    struct thread_launch *launch = malloc(sizeof(*launch));
    *launch = (struct thread_launch){run, arg};
    assert(!pthread_create(thread, NULL, worker_launch, launch));
    worker_thread = *thread; worker_created = true; return KERN_SUCCESS;
}
void thread_set_thread_name(thread_t thread, const char *name) { (void)thread; (void)name; }
static void thread_deallocate(thread_t thread) { (void)thread; }
static void *kalloc_data(size_t bytes, int flags) { return flags & Z_ZERO ? calloc(1, bytes) : malloc(bytes); }
static void kfree_data(void *p, size_t bytes) { (void)bytes; free(p); }
static void hakios_wifi_tell(const char *text) { (void)text; }
#endif
