# Optional Core Image portrait prewarm on the NABU CPU platform

The prior BackgroundBlur capability update stopped the observed Portrait Metal
assertion, but mediaserverd then faulted repeatedly at address zero while creating
a Core Image OpenGL ES context for a different portrait prewarm. The current
platform has no working GPU driver. A software-renderer option is not evidence
that this shipped system has a usable CPU implementation.

Patch 0183 supplies the existing, optional-prewarm configuration value
`TuningParameters.Common.CoreImagePortraitFilter.Version=0` in the fixed J317
CameraSetup resource. The shipped getter defaults to version 1 when the setting
is absent. Its void prewarm dispatcher runs versions 1 and 2, and returns normally
for zero; the original caller also passes zero on its disabled branch. No error
is swallowed, no Metal device is fabricated, and no function code is patched.

The opt-in `nabucicapture=1` migration runs after normal HFS journal replay and
before initproc. `=2` restores the exact original; other values do nothing.
Both complete file identities are fixed. It checks the exact model, guarded
project root device, HFSX volume geometry, valid internal journal, file flags,
inode and all eight known hardlinks. It opens read-only before requesting write
access, refuses unknown bytes, and preserves the existing vnode and links.

Only three binary-plist objects are appended, with the required reference,
offset-table and trailer changes: file length increases from 49124 to 49178.
The generated whole candidate is hash-checked before any write. The public code
contains reconstruction rules and identity digests, not a device plist or backup.
The separate 0182 AVCaptureSession update remains in place.

Normal vnode operations write and resize the target, followed by file/journal
sync, checked device-cache sync, exact-size readback and full digest comparison.
Any failure after a write attempt triggers restoration of the complete source
bytes and size. Restoration failure prevents initproc. A close error after an
otherwise successful operation is reported as `close_failed`; an earlier error
takes precedence over a secondary close error. `CICFG1` records the outcome.
This does not provide power-loss atomicity
or guarantee that the last diagnostic survives a storage failure.

The macOS Actions fixture extracts the actual helpers and uses synthetic bytes
and VFS doubles for migration, refusal and fault recovery. It does not model HFS
persistence or execute an ARM64 device. Local verification is limited to the
downloaded kernel and its build evidence; the next device experiment must prove
configuration application, media-service stability, display progress and an
interactive desktop independently. Successful compilation is not desktop proof.
