// Exercise the extracted production worker, append, send and close functions.
#include <atomic>
#include <cassert>
#include <chrono>
#include <cerrno>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <initializer_list>
#include <pthread.h>
#include <thread>
#include <unistd.h>
#include "nabu_trace_file_protocol.h"
#define p_atomic_read(p) __atomic_load_n((p), __ATOMIC_SEQ_CST)
#define p_atomic_set(p,v) __atomic_store_n((p), (v), __ATOMIC_SEQ_CST)
#define MIN2(a,b) ((a)<(b)?(a):(b))
struct mach_timebase_info_data_t { uint32_t numer, denom; };
struct tu_device {
    pthread_mutex_t submit_mutex;
    std::atomic<uint32_t> control{NativeAdrenoTraceRunning};
    std::atomic<bool> fail_query{false};
    std::atomic<uint32_t> queries{0}, registered{0}, written{0}, ended{0};
    std::atomic<uint64_t> identity_sum{0};
};
#include "production_types.inc"
static uint64_t trace_now(tu_darwin_trace_state *) {
    return std::chrono::steady_clock::now().time_since_epoch().count();
}
static int tu_darwin_trace_call(tu_device *device, uint32_t method,
                                const void *input, size_t, void *output, size_t) {
    if (method == NativeAdrenoMethodQueryTrace) {
        auto *status = static_cast<NativeAdrenoTraceStatus *>(output);
        status->state = device->control.load();
        status->generation = 1;
        device->queries.fetch_add(1);
        return device->fail_query ? -1 : 0;
    }
    if (method == NativeAdrenoMethodRegisterTraceProducer) {
        const int result = pthread_mutex_trylock(&device->submit_mutex);
        assert(result != 0); // Admission still serializes with submissions.
        auto producer = *static_cast<const NativeAdrenoTraceProducer *>(input);
        producer.producer_id = 1;
        *static_cast<NativeAdrenoTraceProducer *>(output) = producer;
        device->registered.fetch_add(1);
        return 0;
    }
    if (method == NativeAdrenoMethodAppendTrace) {
        const auto *batch = static_cast<const NativeAdrenoTraceBatch *>(input);
        assert(batch->generation == 1 && batch->count <= NativeAdrenoTraceBatchEvents);
        device->written.fetch_add(batch->count);
        for (uint32_t i = 0; i < batch->count; ++i)
            device->identity_sum.fetch_add(batch->events[i].command_buffer_id);
        return 0;
    }
    assert(method == NativeAdrenoMethodEndTraceProducer);
    device->ended.fetch_add(1);
    return 0;
}
static std::atomic<uint64_t> broadcasts{0}, signals{0}, waits{0};
static int counted_broadcast(pthread_cond_t *c) {
    broadcasts.fetch_add(1);
    return pthread_cond_broadcast(c);
}
[[maybe_unused]] static int counted_signal(pthread_cond_t *c) {
    signals.fetch_add(1);
    return pthread_cond_signal(c);
}
static int counted_wait(pthread_cond_t *c, pthread_mutex_t *m, const timespec *t) {
    waits.fetch_add(1);
    return pthread_cond_timedwait(c, m, t);
}
#define pthread_cond_broadcast counted_broadcast
#define pthread_cond_signal counted_signal
#define pthread_cond_timedwait counted_wait
#include "production_core.inc"
#undef pthread_cond_broadcast
#undef pthread_cond_signal
#undef pthread_cond_timedwait

template<class F> static void until(F test) {
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(2);
    while (!test()) {
        assert(std::chrono::steady_clock::now() < deadline);
        std::this_thread::sleep_for(std::chrono::milliseconds(1));
    }
}
struct Fixture {
    tu_device device;
    tu_darwin_trace_state state{};
    Fixture(bool active) {
        pthread_mutex_init(&device.submit_mutex, nullptr);
        pthread_mutex_init(&state.mutex, nullptr);
        pthread_cond_init(&state.changed, nullptr);
        state.device = &device;
        if (active) {
            state.producer = {1,1,1,1,0};
            state.active_generation = 1;
        }
    }
    void start() { assert(!pthread_create(&state.worker, nullptr, trace_worker, &state)); }
    void add(uint32_t count) {
        pthread_mutex_lock(&state.mutex);
        NativeAdrenoTraceEvent event{};
        event.clock_domain = NativeAdrenoTraceClockGpuNanoseconds;
        for (uint32_t i=0;i<count;i++) trace_append_locked(&state, 1, event);
        pthread_mutex_unlock(&state.mutex);
    }
    void wake() {
        pthread_mutex_lock(&state.mutex);
        pthread_cond_broadcast(&state.changed);
        pthread_mutex_unlock(&state.mutex);
    }
    void stop() {
        p_atomic_set(&state.stop, true);
        wake();
        assert(!pthread_join(state.worker, nullptr));
        assert(!state.producer.producer_id);
    }
    ~Fixture() {
        pthread_mutex_destroy(&device.submit_mutex);
        pthread_mutex_destroy(&state.mutex);
        pthread_cond_destroy(&state.changed);
    }
};
static void running_drain(bool query_failure) {
    Fixture f(true);
    f.device.fail_query = query_failure;
    pthread_mutex_lock(&f.device.submit_mutex);
    f.add(1024);
    f.start();
    until([&]{ return f.device.queries.load() > 0; });
#if EXPECT_STEADY_DRAIN
    until([&]{ return f.device.written.load() == 1024; });
#else
    std::this_thread::sleep_for(std::chrono::milliseconds(40));
    assert(f.device.written == 0);
#endif
    assert(p_atomic_read(&f.state.active_generation) == 1);
    pthread_mutex_unlock(&f.device.submit_mutex);
    until([&]{ return f.device.written.load() == 1024; });
    f.stop();
    assert(f.device.ended == 1 && f.state.dropped == 0);
}
static void admission() {
    Fixture f(false);
    pthread_mutex_lock(&f.device.submit_mutex);
    f.start();
    until([&]{ return f.device.queries.load() > 0; });
    std::this_thread::sleep_for(std::chrono::milliseconds(20));
    assert(!p_atomic_read(&f.state.active_generation) && f.device.registered == 0);
    pthread_mutex_unlock(&f.device.submit_mutex);
    until([&]{ return p_atomic_read(&f.state.active_generation) == 1; });
    assert(f.device.registered == 1);
    f.stop();
    assert(f.device.ended == 1);
}
static void close_after_retirement() {
    Fixture f(true);
    f.state.pending_submissions = 1;
    f.state.pending_commands = 5;
    f.device.control = 0;
    pthread_mutex_lock(&f.device.submit_mutex);
    f.start();
    until([&]{ return f.device.queries.load() > 0; });
    std::this_thread::sleep_for(std::chrono::milliseconds(20));
    assert(p_atomic_read(&f.state.active_generation) == 1 && f.device.ended == 0);
    pthread_mutex_unlock(&f.device.submit_mutex);
    until([&]{ return !p_atomic_read(&f.state.active_generation); });
    f.add(7); // Late records from a submission admitted to the old window.
    until([&]{ return f.device.written.load() == 7; });
    assert(f.device.ended == 0);
    pthread_mutex_lock(&f.state.mutex);
    assert(f.state.pending_commands == 0 && f.state.unsubmitted_commands == 5);
    f.state.pending_submissions = 0;
    pthread_cond_broadcast(&f.state.changed);
    pthread_mutex_unlock(&f.state.mutex);
    until([&]{ return f.device.ended.load() == 1; });
    f.stop();
    assert(f.device.ended == 1 && f.device.written == 7+EXPECT_SUMMARY_RECORDS);
}
static void stop_on_query_failure() {
    Fixture f(true);
    f.device.fail_query = true;
    f.add(9);
    p_atomic_set(&f.state.stop, true);
    f.start();
    assert(!pthread_join(f.state.worker, nullptr));
    assert(f.device.ended == 1 && f.device.written == 9+EXPECT_SUMMARY_RECORDS);
    assert(!f.state.producer.producer_id && !f.state.active_generation);
}
static void burst_wake_budget() {
    Fixture f(true);
    const auto b = broadcasts.load(), s = signals.load();
    pthread_mutex_lock(&f.state.mutex);
    NativeAdrenoTraceEvent event{};
    for (uint32_t kind : {NativeAdrenoTraceClockGpuNanoseconds,
                          NativeAdrenoTraceClockMonotonicNanoseconds}) {
        event.clock_domain = kind;
        for (uint32_t i=0; i<2048; ++i)
            trace_append_locked(&f.state, 1, event);
        trace_append_locked(&f.state, 1, event); // Full queue still drops once.
    }
    pthread_mutex_unlock(&f.state.mutex);
    assert(f.state.queue_dropped == 2 && f.state.dropped == 2);
    trace_send(&f.state);
    assert(f.device.written == 4096);
#if EXPECT_COALESCED_WAKE
    assert(signals-s == 1 && broadcasts-b == 0);
#else
    assert(signals-s == 0 && broadcasts-b == 4096+64);
#endif
}
static void empty_handoffs() {
    Fixture f(true);
    const auto initial = waits.load();
    f.start();
    until([&]{ return waits > initial; });
    for (uint32_t i=1; i<=200; ++i) {
        const auto previous = waits.load();
        // Taking the same mutex also establishes the waiter entered its wait.
        f.add(1);
        until([&]{ return f.device.written == i && waits > previous; });
    }
    f.stop();
    assert(f.state.dropped == 0 && f.device.written == 200+EXPECT_SUMMARY_RECORDS && f.device.ended == 1);
}
static void concurrent_bursts() {
    Fixture f(true);
    f.start();
    constexpr uint32_t rounds = 100, per_thread = 128, threads = 4;
    for (uint32_t r=0; r<rounds; ++r) {
        std::thread producers[threads];
        for (uint32_t t=0; t<threads; ++t) {
            producers[t] = std::thread([&, r, t]{
                for (uint32_t n=0; n<per_thread; ++n) {
                    NativeAdrenoTraceEvent event{};
                    event.clock_domain = t % 2 ? NativeAdrenoTraceClockGpuNanoseconds :
                                                NativeAdrenoTraceClockMonotonicNanoseconds;
                    event.command_buffer_id = (r*threads+t)*per_thread+n+1;
                    pthread_mutex_lock(&f.state.mutex);
                    trace_append_locked(&f.state, 1, event);
                    pthread_mutex_unlock(&f.state.mutex);
                }
            });
        }
        for (auto &producer : producers) producer.join();
        until([&]{ return f.device.written == (r+1)*threads*per_thread; });
    }
    f.stop();
    const uint64_t n = rounds*threads*per_thread;
    assert(f.state.dropped == 0 && f.device.written == n+EXPECT_SUMMARY_RECORDS);
    assert(f.device.identity_sum == n*(n+1)/2 && f.device.ended == 1);
}
int main() {
    running_drain(false);
    running_drain(true);
    admission();
    close_after_retirement();
    stop_on_query_failure();
    burst_wake_budget();
    empty_handoffs();
    concurrent_bursts();
    printf("{\"passed\":true,\"cases\":8,\"steady_drain_while_submit_locked\":%s,"
           "\"coalesced_wake\":%s,\"burst_events\":4096,\"burst_notifications\":%u,"
           "\"concurrent_records\":51200,\"empty_handoffs\":200}\n",
           EXPECT_STEADY_DRAIN ? "true" : "false", EXPECT_COALESCED_WAKE ? "true" : "false",
           EXPECT_COALESCED_WAKE ? 1u : 4160u);
}
