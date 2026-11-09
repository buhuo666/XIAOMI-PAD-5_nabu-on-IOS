/* Enumerate first; subscribe only to board sensors actually returned by Android.
 * Temporary NDK diagnostic. No calibration, settings or firmware writes. */
#include <android/looper.h>
#include <android/sensor.h>
#include <math.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

static int64_t now_ns(void) {
    struct timespec t;
    clock_gettime(CLOCK_BOOTTIME, &t);
    return (int64_t)t.tv_sec * 1000000000 + t.tv_nsec;
}

static void json_string(const char *s) {
    putchar('"');
    for (; *s; ++s) {
        unsigned char c = (unsigned char)*s;
        if (c == '"' || c == '\\') { putchar('\\'); putchar(c); }
        else if (c < 32) printf("\\u%04x", c);
        else putchar(c);
    }
    putchar('"');
}

struct selected {
    int type;
    const char *chip;
    const char *unit;
    const ASensor *sensor;
    int handle;
    int registered;
    unsigned events;
    int64_t last;
    unsigned nonmonotonic;
};

int main(int argc, char **argv) {
    int seconds = argc > 1 ? atoi(argv[1]) : 12;
    if (seconds < 1 || seconds > 60) return 2;
    setvbuf(stdout, NULL, _IOLBF, 0);
    ASensorManager *manager = ASensorManager_getInstanceForPackage("android");
    if (!manager) return 3;
    ASensorList list;
    int count = ASensorManager_getSensorList(manager, &list);
    if (count < 0) return 4;
    struct selected selected[] = {
        { .type=1, .chip="lsm6dso", .unit="m/s^2" },
        { .type=4, .chip="lsm6dso", .unit="rad/s" },
        { .type=2, .chip="ak0991x", .unit="uT" },
        { .type=5, .chip="tcs3701", .unit="lux" },
        { .type=33171055, .chip="rohm_bu27030", .unit="vendor_back_lux" },
        { .type=33171007, .chip="tcs3701", .unit="vendor_front_factory" },
        { .type=33171057, .chip="rohm_bu27030", .unit="vendor_back_stream" },
    };
    const size_t n = sizeof(selected)/sizeof(selected[0]);
    for (int i=0; i<count; ++i) {
        const ASensor *s = list[i];
        int type = ASensor_getType(s);
        printf("{\"kind\":\"inventory\",\"handle\":%d,\"type\":%d,\"name\":", ASensor_getHandle(s), type);
        json_string(ASensor_getName(s));
        printf(",\"vendor\":"); json_string(ASensor_getVendor(s));
        printf(",\"string_type\":"); json_string(ASensor_getStringType(s));
        printf(",\"resolution\":%.9g,\"min_delay_us\":%d,\"wakeup\":%s,\"reporting_mode\":%d,\"fifo_max\":%d,\"fifo_reserved\":%d}\n",
               ASensor_getResolution(s), ASensor_getMinDelay(s),
               ASensor_isWakeUpSensor(s) ? "true" : "false", ASensor_getReportingMode(s),
               ASensor_getFifoMaxEventCount(s), ASensor_getFifoReservedEventCount(s));
        for (size_t j=0; j<n; ++j) {
            if (type == selected[j].type && strstr(ASensor_getName(s), selected[j].chip) && !ASensor_isWakeUpSensor(s)) {
                selected[j].sensor = s;
                selected[j].handle = ASensor_getHandle(s);
            }
        }
    }
    ALooper *looper = ALooper_prepare(ALOOPER_PREPARE_ALLOW_NON_CALLBACKS);
    ASensorEventQueue *queue = ASensorManager_createEventQueue(manager, looper, 1, NULL, NULL);
    if (!queue) return 5;
    for (size_t j=0; j<n; ++j) {
        struct selected *s = &selected[j];
        if (!s->sensor) {
            printf("{\"kind\":\"absent\",\"type\":%d}\n", s->type);
            continue;
        }
        int delay = ASensor_getMinDelay(s->sensor);
        if (delay < 20000) delay = 20000;
        int rc = ASensorEventQueue_registerSensor(queue, s->sensor, delay, 0);
        s->registered = rc == 0;
        printf("{\"kind\":\"subscribe\",\"type\":%d,\"handle\":%d,\"period_us\":%d,\"status\":%d}\n", s->type, s->handle, delay, rc);
    }
    const int64_t start = now_ns(), end = start + seconds * 1000000000LL;
    printf("{\"kind\":\"start\",\"boottime_ns\":%lld,\"seconds\":%d}\n", (long long)start, seconds);
    while (now_ns() < end) {
        ALooper_pollOnce(100, NULL, NULL, NULL);
        ASensorEvent events[64];
        ssize_t got;
        while (now_ns() < end && (got=ASensorEventQueue_getEvents(queue, events, 64)) > 0) {
            for (ssize_t i=0; i<got; ++i) {
                const ASensorEvent *e = &events[i];
                for (size_t j=0; j<n; ++j) {
                    struct selected *s = &selected[j];
                    if (!s->registered || e->sensor != s->handle || e->type != s->type) continue;
                    if (s->events && e->timestamp <= s->last) ++s->nonmonotonic;
                    s->last = e->timestamp; ++s->events;
                    printf("{\"kind\":\"event\",\"type\":%d,\"handle\":%d,\"timestamp_ns\":%lld,\"received_boottime_ns\":%lld,\"data\":[",
                           e->type, e->sensor, (long long)e->timestamp, (long long)now_ns());
                    int dimensions = s->type==5 ? 1 : 3;
                    for (int k=0; k<dimensions; ++k) {
                        if (k) putchar(',');
                        if (isfinite(e->data[k])) printf("%.9g", e->data[k]); else printf("null");
                    }
                    printf("]");
                    if (s->type==1 || s->type==2 || s->type==4) printf(",\"accuracy\":%d", e->vector.status);
                    printf("}\n");
                }
            }
        }
    }
    for (size_t j=0; j<n; ++j) {
        struct selected *s = &selected[j];
        if (s->registered) ASensorEventQueue_disableSensor(queue, s->sensor);
        printf("{\"kind\":\"result\",\"type\":%d,\"handle\":%d,\"present\":%s,\"subscribed\":%s,\"events\":%u,\"nonmonotonic\":%u,\"unit\":",
               s->type, s->handle, s->sensor?"true":"false", s->registered?"true":"false", s->events, s->nonmonotonic);
        json_string(s->unit); printf("}\n");
    }
    ASensorManager_destroyEventQueue(manager, queue);
    puts("{\"kind\":\"complete\",\"subscriptions_closed\":true}");
    return 0;
}
