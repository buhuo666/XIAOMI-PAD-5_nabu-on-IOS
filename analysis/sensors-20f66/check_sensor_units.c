#include "../../userland/nabu/src/sensor_units.h"
#include <assert.h>
#include <stdio.h>

static void near(double actual, double expected)
{
    assert(fabs(actual-expected) < 1e-10);
}

int main(void)
{
    const int8_t identity[3] = {1, 2, 3}, rotated[3] = {-2, 1, 3}, invalid[3] = {1, 1, 3};
    struct nabu_sensor_sample s = {.mach_timestamp = 123, .value = {0, 0, 9.80665}};
    double out[3];
    assert(!nabu_sensor_convert(NABU_SENSOR_ACCELEROMETER, identity, &s, out));
    near(out[2], -1);
    s.value[0] = 9.80665; s.value[1] = s.value[2] = 0;
    assert(!nabu_sensor_convert(NABU_SENSOR_ACCELEROMETER, rotated, &s, out));
    near(out[0], 0); near(out[1], -1);
    s.value[0] = 1; s.value[1] = 2; s.value[2] = 3;
    assert(!nabu_sensor_convert(NABU_SENSOR_GYROSCOPE, rotated, &s, out));
    near(out[0], -2); near(out[1], 1); near(out[2], 3);
    s.value[0] = -125; s.value[1] = -114; s.value[2] = 165;
    assert(!nabu_sensor_convert(NABU_SENSOR_MAGNETOMETER, identity, &s, out));
    near(out[0], -125); near(out[1], -114); near(out[2], 165);
    s.value[0] = 16.1;
    assert(!nabu_sensor_convert(NABU_SENSOR_AMBIENT_LIGHT, NULL, &s, out)); near(out[0], 16.1);
    assert(nabu_sensor_convert(NABU_SENSOR_ACCELEROMETER, invalid, &s, out) == EINVAL);
    s.mach_timestamp = 0;
    assert(nabu_sensor_convert(NABU_SENSOR_ACCELEROMETER, identity, &s, out) == EINVAL);
    s.mach_timestamp = 123; s.value[0] = NAN;
    assert(nabu_sensor_convert(NABU_SENSOR_GYROSCOPE, identity, &s, out) == ERANGE);
    s.value[0] = 32768;
    assert(nabu_sensor_convert(NABU_SENSOR_MAGNETOMETER, identity, &s, out) == ERANGE);
    s.value[0] = -1;
    assert(nabu_sensor_convert(NABU_SENSOR_AMBIENT_LIGHT, NULL, &s, out) == ERANGE);
    puts("sensor units: SI/sign/explicit-axis mapping, live timestamp and HID range checks passed");
    return 0;
}
