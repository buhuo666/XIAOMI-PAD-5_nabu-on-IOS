# GPU186: set framebuffer pacing and advertised refresh to 120 Hz

User explicitly requested the kernel's 120 Hz setting after GPU185 measured
both physical DSI interfaces at approximately 120 Hz (8.330714 ms per frame).

The canonical Nabu boot configuration and this trial set `fb_hz=120` and
`fb_ca_hz=120`. The existing kernel already consumes these tunables: the first
controls framebuffer timing elements, presenter pacing and software vsync;
the second controls the CoreAnimation `IOMFBDisplayRefresh` intervals.

The Nabu source overlay also changes `kFBRefreshHz` from 60 to 120 for future
builds. Its patch applies successfully to the pinned source. Both TOML files
parse with exactly one of each 120 Hz argument. No new test suite is added
for the constant/configuration change.

GPU186 reuses the already qualified GPU185 kernel and GPU180 bootstrap.
There is no kernel rebuild or panel-register write in this trial. Runtime
acceptance requires the actual kernel log to report 120 Hz for both the
advertised refresh and software pacing, together with desktop/touch feedback.

This setting does not implement hardware-vblank notifications, DPU page flips,
variable refresh, or prove 120 distinct rendered frames each second. Those
display changes remain separate from the qualified GPU184 direct-IOSurface
page-sharing path. State: `log/host/gpu-v186/continuation.json`.

## Runtime result

GPU186 was deployed/read back and temporarily booted. GPU readiness passed;
the user confirmed desktop/touch but little improvement and/or remaining
tearing. The native `com.apple.mobile.diagnostics_relay` service returned the
live IORegistry entry when queried with `Request=IORegistry` and
`EntryClass=IOMobileFramebuffer` (EntryName did not match):

- Horizontal/vertical active pixels: 1600/2560.
- Both SyncRate and PreciseSyncRate: 7864320, exactly 120 in 16.16.
- IOMFBDisplayRefresh minimum/maximum/step: 35791394, approximately 1/120 s
  in 32.32; displayRefreshStepMachTime: 159999 ticks.

Receipt: `log/host/gpu-v186/display-ioregistry-class.json`; original reply is
`display-ioregistry-class.plist`. This confirms the requested runtime setting;
it is not a measurement of delivered application FPS or scanout retirement.

The actual generated ADT was parsed separately: it has no display refresh-rate
property. DarwinBoot passes these settings in DARWIN_BOOT_ARGS.CommandLine,
separately from DeviceTree. No invented ADT property was added. See
`log/host/gpu-v186/device-tree-check.json`.

The device remains in iPadOS with the 120 Hz setting active. The current
kernel log slot has not been collected or cleared; GPU retains device
ownership. Collect this slot before preparing any subsequent device trial.
