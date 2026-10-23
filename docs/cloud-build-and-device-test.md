# Authorized cloud kernel build and bounded device diagnostic

On 2026-10-23 the owner explicitly authorized this project's GitHub macOS
kernel builds and subsequent conditional physical-device diagnostics.
This supersedes the earlier local-only restriction for the necessary CI
branch and Actions runs. It does not authorize unrelated remote updates.

The kernel build pins Xcode 15.0.1 (15A507), xnu-8796.141.3, ARM64/NABU and
the complete numbered project patch set. A successful source test and build
produce `build-manifest.json`; use `tools/kernel-build-evidence.py verify`
with the exact source commit, run ID and kernel SHA-256 after downloading.
The loader workflow requires these explicit inputs and a successful kernel
workflow from the same commit. It never silently selects the historical kernel.
The optional QEMU experiment remains emulator evidence only.

Device constraints remain those in `device-test-scope.md`: persistent project
writes only to nabu_esp (sda35, 4 GiB) and nabu_system (sda36, 60 GiB), with
live identity/GPT/geometry verification. This diagnostic does not format the
system partition, change GPT, boot slots, BCD, BootOrder, BootNext or firmware.
Recovery may only be temporarily RAM-booted using the verified image.

Neither a successful manifest nor a QEMU result authorizes a firmware launch.
Audit the exact existing UEFI image's automatic boot, log, variable and block
write paths first. Unresolved paths prohibit its execution. Do not install
fallback EFI files or startup scripts. Run the probe only through an audited
entry, and bind the actual device report to the probe/kernel identities.

The first hardware kernel diagnostic keeps the guarded 256 MiB, single-CPU,
no-storage profile with fresh RNG seed and `nabulog=0 ufsrw=0 cpus=1`.
Do not apply the emulator's 512 MiB configuration to the tablet. Report probe
execution, XNU entry, early VM progress and iPadOS userspace as separate
observations; a blank screen is an unconfirmed result.
