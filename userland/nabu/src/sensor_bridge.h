#ifndef NABU_SENSOR_BRIDGE_H
#define NABU_SENSOR_BRIDGE_H

#include <CoreFoundation/CoreFoundation.h>
#include <stdbool.h>
#include "sensor_units.h"

typedef struct __IOHIDEventSystemClient *IOHIDEventSystemClientRef;
struct nabu_sensor_bridge;

struct nabu_sensor_description {
    enum nabu_sensor_kind kind;
    const char *product;
    const char *manufacturer;
    uint64_t physical_suid[2];
    int8_t axes[3];
    /* Actual IORegistry identity read from the opened NabuSensorSource.
     * These identify the provider; they never replace the virtual HID ID. */
    uint64_t source_registry_id;
    uint32_t source_generation;
};

enum nabu_sensor_control {
    NABU_SENSOR_REPORT_INTERVAL_US,
    NABU_SENSOR_BATCH_INTERVAL_US,
};

/* Runs on the owner's serial HID queue. Return true only if the live backend
 * actually accepted this setting; do not block waiting for an absent SUID.
 * Returning false preserves the old property and lets the caller record failure.
 */
typedef bool (*nabu_sensor_apply_control)(void *context,
    enum nabu_sensor_control control, uint64_t microseconds);

/* The owner supplies a scheduled, authorized HID client and keeps it alive.
 * All functions and client callbacks must run on that SAME serial queue.
 * Allocation alone publishes no hardware. No launch job or constructor exists.
 */
struct nabu_sensor_bridge *nabu_sensor_bridge_create(
    IOHIDEventSystemClientRef client, const struct nabu_sensor_description *description,
    nabu_sensor_apply_control apply_control, void *context);

/* Call only for a currently discovered physical SUID's real live sample.
 * The first accepted sample creates the service. 0 means dispatched; EAGAIN
 * means pending event-server open, EIO means creation/dispatch failed.
 * There is no internal wait or retry loop. A later sample replaces a pending
 * sample, preserving its original timestamp. ESTALE rejects reordered samples.
 */
int nabu_sensor_bridge_publish(struct nabu_sensor_bridge *bridge,
    const struct nabu_sensor_sample *sample);

/* Drain a still-pending sample once after the asynchronous service opens.
 * Call on a bounded owner timer for on-change sensors. Never resends an event
 * that was already dispatched, and never substitutes the current timestamp.
 */
int nabu_sensor_bridge_flush(struct nabu_sensor_bridge *bridge);

/* On SUID loss, transport failure, stale continuous data or explicit stop:
 * invalidate first, remove the service and clear its cached sample. Failed
 * removal returns EIO and can be retried; no new samples can revive this object.
 */
int nabu_sensor_bridge_invalidate(struct nabu_sensor_bridge *bridge);

/* Only after invalidation AND the owner has unscheduled/drained its HID client
 * callbacks. Returns EBUSY if a service is still attached. The callback context
 * and bridge storage must live until then; IOHID retains an unowned refcon.
 */
int nabu_sensor_bridge_destroy(struct nabu_sensor_bridge *bridge);

#endif
