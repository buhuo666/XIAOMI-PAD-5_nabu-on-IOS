#!/usr/bin/env python3
"""Fetch and hash-check the pinned iPadOS 20G81 SystemOS component."""

import hashlib
import io
from pathlib import Path
import sys
import urllib.request
import zipfile


URL = (
    "https://updates.cdn-apple.com/2023SummerFCS/fullrestores/042-44385/"
    "366890C4-D9B5-4938-B399-C19FB58DBEE0/"
    "iPad_Pro_HFR_16.6.1_20G81_Restore.ipsw"
)
MANIFEST_SHA256 = (
    "284e991153baa96f3a19ddb57b828ccddf871b4886aff9d9f936f957c19127c5"
)
MEMBER = "096-56782-083.dmg"
EXPECTED_BYTES = 2665480192
EXPECTED_SHA256 = "bae1f451b77c17f8984980236ab577f89a8a4c5407bdc25c4242a34e11b0e7af"
BLOCK_BYTES = 8 << 20


class RemoteIPSW(io.RawIOBase):
    """Read a remote IPSW using validated HTTP range requests."""

    def __init__(self):
        self.position = 0
        self.cache = {}
        request = urllib.request.Request(
            URL, headers={"Range": "bytes=0-0", "Accept-Encoding": "identity"}
        )
        with urllib.request.urlopen(request, timeout=120) as response:
            if response.status != 206:
                raise ValueError("IPSW server did not honor the initial range request")
            self.size = int(response.headers["Content-Range"].split("/")[1])

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self.position

    def seek(self, offset, whence=0):
        self.position = (0, self.position, self.size)[whence] + offset
        if not 0 <= self.position <= self.size:
            raise ValueError("invalid IPSW seek")
        return self.position

    def readinto(self, buffer):
        count = min(len(buffer), self.size - self.position)
        written = 0
        while written < count:
            index, offset = divmod(self.position, BLOCK_BYTES)
            if index not in self.cache:
                start = index * BLOCK_BYTES
                end = min(start + BLOCK_BYTES, self.size) - 1
                request = urllib.request.Request(
                    URL,
                    headers={
                        "Range": f"bytes={start}-{end}",
                        "Accept-Encoding": "identity",
                    },
                )
                with urllib.request.urlopen(request, timeout=120) as response:
                    expected_range = f"bytes {start}-{end}/{self.size}"
                    if (
                        response.status != 206
                        or response.headers.get("Content-Range") != expected_range
                    ):
                        raise ValueError("IPSW range response mismatch")
                    data = response.read(end - start + 2)
                if len(data) != end - start + 1:
                    raise ValueError("short IPSW range response")
                if len(self.cache) >= 4:
                    self.cache.pop(next(iter(self.cache)))
                self.cache[index] = data
            data = self.cache[index][offset : offset + count - written]
            buffer[written : written + len(data)] = data
            written += len(data)
            self.position += len(data)
        return written


def fetch(output):
    output.mkdir(parents=True, exist_ok=True)
    destination = output / "systemos.dmg"
    if destination.exists():
        raise ValueError("refusing to overwrite an existing SystemOS component")

    created = False
    try:
        with RemoteIPSW() as remote, zipfile.ZipFile(remote) as archive:
            manifest = archive.read("BuildManifest.plist")
            if hashlib.sha256(manifest).hexdigest() != MANIFEST_SHA256:
                raise ValueError("20G81 BuildManifest digest mismatch")
            member = archive.getinfo(MEMBER)
            if member.file_size != EXPECTED_BYTES:
                raise ValueError("20G81 SystemOS component size mismatch")
            digest = hashlib.sha256()
            with archive.open(member) as source, destination.open("xb") as target:
                created = True
                while chunk := source.read(BLOCK_BYTES):
                    target.write(chunk)
                    digest.update(chunk)
            if digest.hexdigest() != EXPECTED_SHA256:
                raise ValueError("20G81 SystemOS component digest mismatch")
    except Exception:
        if created:
            destination.unlink(missing_ok=True)
        raise

    print(
        f"Verified official 20G81 SystemOS component: "
        f"{EXPECTED_BYTES} bytes, SHA-256 {EXPECTED_SHA256}",
        flush=True,
    )


if __name__ == "__main__":
    fetch(Path(sys.argv[1]))
