#!/usr/bin/env python3
"""Extract explicit boot messages without treating them as a completed OS boot."""
import argparse
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET


def hfs_wait_message(rows):
    for index, row in enumerate(rows):
        if not row["text"].startswith("Waiting on "):
            continue
        text = row["text"][len("Waiting on "):]
        last_row = row["row"]
        for following in rows[index + 1:index + 4]:
            if "</dict>" in text or following["row"] != last_row + 1:
                break
            text += following["text"]
            last_row = following["row"]
        try:
            node = ET.fromstring(text)
        except ET.ParseError:
            continue
        children = list(node)
        if node.tag != "dict" or len(children) % 2:
            continue
        values = {}
        for key, value in zip(children[::2], children[1::2]):
            if key.tag != "key" or value.tag != "string" or key.text in values:
                break
            values[key.text] = value.text
        else:
            if values.get("IOProviderClass") == "IOMedia" and values.get("Content") == "Apple_HFS":
                return True
    return False


def summarize(console, cpu_count_state=None):
    rows = console.get("decoded_rows", [])
    lines = {row["text"] for row in rows}
    return {
        "cpu_count_published": cpu_count_state == 1,
        "cpu_sgi_self_test_message_observed": any(
            re.fullmatch(r"NABU CPU: (\d+)/\1 CPUs initialized, SGI1 verified", line)
            and not line.startswith("NABU CPU: 0/") for line in lines
        ),
        "bsd_init_message_observed": "NABU BSD: bsd_init enter" in lines,
        "bsd_autoconf_complete_message_observed": "NABU BSD: after bsd_autoconf" in lines,
        "root_device_search_message_observed": "NABU: setconf before IOFindBSDRoot" in lines,
        "hfs_root_wait_message_observed": hfs_wait_message(rows),
        "limits": (
            "Captured messages can wrap in framebuffer row order. They are not a chronological "
            "trace, a current stack, a mounted root, or a userspace/physical-device boot verdict."
        ),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--console", type=Path, required=True)
    parser.add_argument("--cpu-count-state", type=int)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit(f"Refusing to overwrite {args.output}")
    console = json.loads(args.console.read_text(encoding="utf-8"))
    report = summarize(console, args.cpu_count_state)
    report["kernel_sha256"] = console.get("kernel_sha256")
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
