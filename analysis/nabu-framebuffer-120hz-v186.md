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
