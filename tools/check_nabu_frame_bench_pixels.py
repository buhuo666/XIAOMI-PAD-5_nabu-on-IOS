"""Recompute merged-alpha differences and barcode correctness from device raw images."""
import argparse
import json
from collections import Counter
from pathlib import Path


def check(folder):
    metadata = json.loads((folder / 'merge-pixel-check.json').read_text())
    width, height = metadata['width'], metadata['height']
    if (width, height, metadata['pixel_format'], metadata['bytes_per_row']) != (1600, 2560, 'BGRA8Unorm', 6400):
        raise ValueError('Incorrect native-resolution pixel check')
    cases = []
    for case in metadata['cases']:
        left = (folder / case['baseline_raw']).read_bytes()
        right = (folder / case['merged_raw']).read_bytes()
        if len(left) != width * height * 4 or len(right) != len(left):
            raise ValueError('Incomplete pixel readback')
        histogram = Counter(max(abs(a - b), abs(c - d), abs(e - f))
                            for a, b, c, d, e, f in zip(left[0::4], right[0::4], left[1::4],
                                                       right[1::4], left[2::4], right[2::4]))
        alpha = sum(a != 255 or b != 255 for a, b in zip(left[3::4], right[3::4]))
        barcode = 0
        for y in range(64):
            for x in range(width):
                expected = 255 if (case['frame'] >> (x // 100)) & 1 else 0
                offset = (y * width + x) * 4
                barcode += sum(left[offset + c] != expected or right[offset + c] != expected for c in range(3))
        recorded = {row['maximum_rgb_delta']: row['pixels'] for row in case['histogram']}
        different = width * height - histogram[0]
        maximum = max(histogram)
        if (dict(histogram) != recorded or different != case['different_rgb_pixels']
                or maximum != case['maximum_rgb_delta'] or alpha != case['alpha_errors']
                or barcode != case['barcode_channel_errors']):
            raise ValueError('Device summary differs from independently read pixels')
        cases.append({'case': case['case'], 'pixels': width * height,
                      'different_rgb_pixels': different, 'maximum_rgb_delta': maximum,
                      'alpha_errors': alpha, 'barcode_channel_errors': barcode, 'histogram': dict(histogram)})
    complete = metadata['complete'] and len(cases) == 4 and not metadata['error']
    exact = complete and all(not c['different_rgb_pixels'] and not c['alpha_errors']
                             and not c['barcode_channel_errors'] for c in cases)
    if exact != metadata['byte_exact']:
        raise ValueError('Byte-exact claim differs from raw images')
    return {'raw_summary_verified': True, 'complete': complete, 'byte_exact': exact,
            'maximum_rgb_delta': max((c['maximum_rgb_delta'] for c in cases), default=None),
            'cases': cases, 'scope': 'GPU BGRA8 images only; timing and display cadence are independent checks'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = check(args.input)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
