#ifndef NABU_SENSOR_UNITS_H
#define NABU_SENSOR_UNITS_H

#include <errno.h>
#include <math.h>
#include <stdint.h>

enum nabu_sensor_kind {
    NABU_SENSOR_ACCELEROMETER,
    NABU_SENSOR_GYROSCOPE,
    NABU_SENSOR_MAGNETOMETER,
    NABU_SENSOR_AMBIENT_LIGHT,
};

/* A live SSC sample after its timestamp has been anchored to THIS XNU boot.
 * accel: proper acceleration in m/s^2; gyro: rad/s; raw mag: microtesla;
 * ambient light: lux in value[0]. Neither an Android snapshot nor UTC is input.
 */
struct nabu_sensor_sample {
    uint64_t mach_timestamp;
    double value[3];
};

static inline int nabu_sensor_validate_axes(enum nabu_sensor_kind kind, const int8_t axes[3])
{
    if (kind == NABU_SENSOR_AMBIENT_LIGHT)
        return 0;
    if (kind < NABU_SENSOR_ACCELEROMETER || kind > NABU_SENSOR_MAGNETOMETER || !axes)
        return EINVAL;
    unsigned used = 0;
    for (unsigned i = 0; i < 3; ++i) {
        int axis = axes[i];
        unsigned index = (unsigned)(axis < 0 ? -axis : axis);
        if (index < 1 || index > 3 || (used & (1u << index)))
            return EINVAL;
        used |= 1u << index;
    }
    return 0;
}

/* Destination portrait device X/Y/Z selects signed source axes 1/2/3.
 * Supply the actual board transform; there is deliberately no default matrix.
 * CoreMotion acceleration uses the gravity-acceleration sign convention, so
 * proper acceleration changes sign after mapping and is converted to g.
 * Verify this board's orientation with the six stationary faces before release.
 */
static inline int nabu_sensor_convert(enum nabu_sensor_kind kind,
    const int8_t axes[3], const struct nabu_sensor_sample *sample, double out[3])
{
    if (!sample || !out || !sample->mach_timestamp)
        return EINVAL;
    if (kind == NABU_SENSOR_AMBIENT_LIGHT) {
        if (!isfinite(sample->value[0]) || sample->value[0] < 0 ||
            sample->value[0] > UINT32_MAX)
            return ERANGE;
        out[0] = sample->value[0];
        out[1] = out[2] = 0;
        return 0;
    }
    int error = nabu_sensor_validate_axes(kind, axes);
    if (error)
        return error;
    for (unsigned i = 0; i < 3; ++i) {
        int axis = axes[i];
        unsigned index = (unsigned)(axis < 0 ? -axis : axis);
        double value = sample->value[index - 1];
        if (!isfinite(value))
            return ERANGE;
        value *= axis < 0 ? -1.0 : 1.0;
        if (kind == NABU_SENSOR_ACCELEROMETER)
            value /= -9.80665;
        /* The verified IOHID constructors encode signed 16.16 values. */
        if (value < -32768.0 || value > 32767.9999847412109375)
            return ERANGE;
        out[i] = value;
    }
    return 0;
}

#endif
