# Xiaomi Pad 5 (nabu) XNU build

This repository is a GitHub Actions build harness for the experimental xnu-8796.141.3 (macOS 13.5 generation) nabu kernel patches.

The workflow uploads a raw arm64 XNU kernel and build provenance. It does not create a prelinked kernel, IPSW root filesystem, or bootable image, and it does not flash a device. Hardware boot remains unverified.

Run **Actions → build-xnu-8796 → Run workflow** to select RELEASE, DEVELOPMENT, or DEBUG. The workflow also runs on pushes to `main` that change the numbered device patches or build workflow.
