// SPDX-License-Identifier: BSD-2-Clause-Patent
#ifndef NABU_SENSOR_HID_H
#define NABU_SENSOR_HID_H
#include <stdint.h>

/* Current 8796 has no IOHIDEventService class. This is the shared ABI of a real
 * NabuSensorSource IOService, consumed by a userspace HID bridge. No IOKit types
 * occur here. Kind values exactly match userland/nabu/src/sensor_units.h. */
enum {
    NabuSensorSourceAbi = 1,
    NabuSensorAccelerometer = 0, NabuSensorGyroscope = 1,
    NabuSensorMagnetometer = 2, NabuSensorAmbientLight = 3,
    NabuSensorKindCount = 4,
    NabuSensorSourceOpenType = 0x534e,
    NabuSensorSourceQueueMemory = 0, NabuSensorSourceQueueNotification = 0,
    NabuSensorSourceGetStatus = 0, NabuSensorSourceSetControl = 1,
    NabuSensorReportIntervalUs = 0, NabuSensorBatchIntervalUs = 1,
    NabuSensorRecordSample = 1, NabuSensorRecordInvalidated = 2,
    NabuSensorRecordCurrentSnapshot = 1,
};

/* Consumer order: open, map memory type0, register notification type0, drain
 * the queue once before waiting (the initial snapshot predates the port), then
 * drain after each notification. Query Status.active as well as record_type:
 * a full queue may drop an invalidation record, but never the active=false
 * status. A snapshot keeps the original sample sequence and timestamp. */

struct NabuSensorDescription {
    uint32_t abi_version;
    uint32_t kind;
    uint64_t physical_suid[2]; /* low, high; obtained from this boot's SSC */
    char product[48];
    char manufacturer[32];
};

struct NabuSensorRecord {
    uint32_t kind;
    uint32_t record_type;
    uint32_t value_count;
    uint32_t accuracy;       /* original SSC status, never an Apple gyro flag */
    uint64_t sequence;       /* assigned by this transport, including invalidation */
    uint64_t ssc_ticks;
    uint64_t mach_timestamp; /* mapped and verified by the producer for this boot */
    uint32_t value_bits[4];  /* IEEE754: accel m/s^2, gyro rad/s, mag uT, ALS lux */
    uint32_t reason;         /* producer's IOReturn on an invalidation record */
    uint32_t flags;
};

struct NabuSensorStatus {
    struct NabuSensorDescription description;
    struct NabuSensorRecord latest;
    uint64_t accepted_samples;
    uint64_t enqueued_records;
    uint64_t dropped_records;
    uint64_t report_interval_us;
    uint64_t batch_interval_us;
    uint32_t active;
    uint32_t generation;
    uint32_t invalidation_reason;
    uint32_t reserved;
};

struct NabuSensorControlRequest {
    uint32_t control;
    uint32_t reserved;
    uint64_t microseconds;
};

#if defined(__cplusplus)
static_assert(sizeof(NabuSensorDescription)==104, "sensor description ABI");
static_assert(sizeof(NabuSensorRecord)==64, "sensor record ABI");
static_assert(sizeof(NabuSensorStatus)==224, "sensor status ABI");
static_assert(sizeof(NabuSensorControlRequest)==16, "sensor control ABI");
extern "C" {
#endif

/* All result codes are IOReturn values (zero is success). initialize and submit
 * run on the SSC owner's serial sleepable worker, never an interrupt callback.
 * initialize registers classes only; no sensor service appears before submit.
 * The owner calls submit only after physical discovery and a real valid sample.
 * The producer supplies kind/count/accuracy/SSC tick/Mach time/raw bits. Other
 * record fields are assigned by the transport. No floating point runs here. */
int32_t nabu_sensor_hid_initialize(void);
int32_t nabu_sensor_hid_submit(const struct NabuSensorDescription *, const struct NabuSensorRecord *);
int32_t nabu_sensor_hid_invalidate(uint32_t kind, int32_t reason);

/* Called from the IOUserClient method context without the transport lock held.
 * Return success only when the SSC backend actually accepted the setting.
 * A backend that cannot safely service this caller must return NotReady or
 * Unsupported, not enqueue work and return a false success. */
typedef int32_t (*NabuSensorControlHandler)(void *, uint32_t kind, uint32_t control, uint64_t microseconds);
void nabu_sensor_hid_set_control_handler(NabuSensorControlHandler, void *context);

#if defined(__cplusplus)
}
#endif
#endif
