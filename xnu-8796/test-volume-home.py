#!/usr/bin/env python3
"""Compile the actual Home-chord state machine; no kernel or device access."""
import argparse
from pathlib import Path
import subprocess
import tempfile

TEST = r"""
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include "nabu_key_chord.h"
#define MS(x) ((uint64_t)(x) * 1000000ULL)

static unsigned step(struct nabu_key_chord *s, int valid, int up, int down, unsigned ms)
{
    return nabu_key_chord_step(s, valid != 0, up != 0, down != 0, MS(ms));
}

int main(void)
{
    struct nabu_key_chord s = {0};
    /* Boot-held switches must not generate Home. */
    assert(step(&s, 1, 1, 1, 0) == 0);
    assert(step(&s, 1, 1, 1, 10000) == 0);
    assert(step(&s, 1, 0, 0, 10020) == 0);
    /* Exact one-second monotonic threshold, not a count of samples. */
    assert(step(&s, 1, 1, 1, 10100) == 0);
    assert(step(&s, 1, 1, 1, 11099) == 0);
    assert(step(&s, 1, 1, 1, 11100) == NABU_HOME_DOWN);
    assert(step(&s, 1, 1, 1, 11199) == 0);
    assert(step(&s, 1, 1, 1, 11200) == NABU_HOME_UP);
    for (unsigned ms = 11220; ms < 30000; ms += 20)
        assert(step(&s, 1, 1, 1, ms) == 0);
    /* A partial release does not rearm; both switches must be released. */
    assert(step(&s, 1, 0, 1, 30000) == 0);
    assert(step(&s, 1, 1, 1, 30020) == 0);
    assert(step(&s, 1, 1, 1, 35000) == 0);
    assert(step(&s, 1, 0, 0, 35020) == 0);
    assert(step(&s, 1, 1, 1, 35100) == 0);
    assert(step(&s, 1, 1, 1, 36100) == NABU_HOME_DOWN);
    assert(step(&s, 1, 0, 1, 36120) == NABU_HOME_UP);
    /* Short or one-key presses never produce a Home event. */
    s = (struct nabu_key_chord){0};
    assert(step(&s, 1, 0, 0, 0) == 0);
    assert(step(&s, 1, 1, 1, 10) == 0);
    assert(step(&s, 1, 0, 1, 1009) == 0);
    assert(step(&s, 1, 1, 1, 1010) == 0);
    assert(step(&s, 1, 1, 1, 2009) == 0);
    assert(step(&s, 1, 0, 0, 2010) == 0);
    for (unsigned ms = 2020; ms < 10000; ms += 20)
        assert(step(&s, 1, 1, 0, ms) == 0);
    assert(step(&s, 1, 0, 0, 10000) == 0);
    for (unsigned ms = 10020; ms < 20000; ms += 20)
        assert(step(&s, 1, 0, 1, ms) == 0);
    /* Failed reads cancel timing, release Home, and disarm until release. */
    s = (struct nabu_key_chord){0};
    assert(step(&s, 1, 0, 0, 0) == 0);
    assert(step(&s, 1, 1, 1, 100) == 0);
    assert(step(&s, 0, 1, 1, 1099) == 0);
    assert(step(&s, 1, 1, 1, 2100) == 0);
    assert(step(&s, 1, 0, 0, 2200) == 0);
    assert(step(&s, 1, 1, 1, 2300) == 0);
    assert(step(&s, 1, 1, 1, 3300) == NABU_HOME_DOWN);
    assert(step(&s, 0, 1, 1, 3320) == NABU_HOME_UP);
    assert(step(&s, 1, 1, 1, 5000) == 0);
    /* A clock rollback cancels a pending gesture. */
    s = (struct nabu_key_chord){0};
    assert(step(&s, 1, 0, 0, 0) == 0);
    assert(step(&s, 1, 1, 1, 100) == 0);
    assert(step(&s, 1, 1, 1, 99) == 0);
    assert(step(&s, 1, 1, 1, 10000) == 0);
    return 0;
}
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--xnu-source", type=Path, required=True)
    parser.add_argument("--cc", default="clang")
    args = parser.parse_args()
    source = (args.xnu_source / "bsd/dev/nabu_keys.c").read_text()
    for fragment in ("#define KEYS_GPIO_BASE   0xc500u",
                     "#define KEYS_GPIO_PPID   0x0c5u",
                     "keys_find_apid(KEYS_GPIO_PPID, count)",
                     "nabu_key_chord_step(&chord, pok && gok,",
                     "clock_get_uptime(&now_abs)",
                     "absolutetime_to_nanoseconds(now_abs, &now_ns)",
                     "nabu_hid_key(3, 0)", "nabu_hid_key(3, 1)"):
        if fragment not in source:
            raise ValueError("Missing actual nabu GPIO/chord integration: " + fragment)
    if "keys_find_apid(0x4c1" in source or "volume_chord_polls" in source:
        raise ValueError("Old hardware or poll-count timing remains")
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory)
        (path / "test.c").write_text(TEST)
        subprocess.run([args.cc, "-std=c11", "-Wall", "-Wextra", "-Werror",
                        "-I", str(args.xnu_source / "bsd/dev"),
                        str(path / "test.c"), "-o", str(path / "test")], check=True)
        subprocess.run([str(path / "test")], check=True)
    print("Actual Home-chord header passed: GPIO6/SID0, 1s timing, one tap, release/rearm, failed reads.")


if __name__ == "__main__":
    main()
