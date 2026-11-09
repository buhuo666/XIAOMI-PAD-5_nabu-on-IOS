# Hall open-to-lock-screen policy (20F66)

The user requested that opening the cover wake to the lock screen, without
automatically returning to the desktop. Hall02 already verified GPIO9 input,
native HES delivery, closing-to-lock, display off/on, a sustained closed cover,
power/volume buttons, and touch. Its original SmartCover path automatically
unlocked on opening; this was also visible as `deviceIsLocked=YES` on closing
followed by `deviceIsLocked=NO` on opening.

## Original implementation evidence

These are ordinary local Capstone and Objective-C metadata observations from
the retained iPad7,11 / 16.5 / 20F66 shared cache, not REA Evidence records or
execution of the new policy. REA's connected Windows session has no usable
native provider. No provider or client configuration was changed.

The source image is `/System/Library/PrivateFrameworks/SpringBoard.framework/SpringBoard`
within `OS/ipados/16.5-20F66-iPad7_11/userland/systemos/System/Library/Caches/com.apple.dyld/`.
The relevant code and method lists map to `dyld_shared_cache_arm64.21`.
Original names came from the retained local-symbol inventory in
`log/host/wireless-v135/signal-contract/SpringBoard-symbols.json`.
Bounded disassembly and method metadata are saved under
`log/host/hall-lockscreen-20261110/`; address-to-file mapping uses the existing
cache manifest, through `log/host/wireless-v130/ioctl-contract/inspect_contract.py`.
Method encodings were read from the class's method list by matching its exact
implementation address to the original symbol. Cached selector-name offsets
were not decoded or treated as ordinary Mach-O field-relative strings.

| Address | Observed behavior |
| --- | --- |
| `0x1c42597e0` | `-[SpringBoard _smartCoverDidOpen:]` clears the closed flag, passes source **3** to `_keyboardOrCaseLatchWantsToAttemptUnlock:`, releases the cover HID assertion, and notifies observers of the open state. |
| `0x1c4259c84` | Enqueues the original workspace event. Its condition block at `0x1c4259e48` checks `allowCaseLatchLockAndUnlock` for source 3. |
| `0x1c4259d14` | The event handler retains source 3 and calls `unlockUIFromSource:withOptions:` with `SBUIUnlockOptionsTurnOnScreenFirstKey` and `SBUIUnlockOptionsStartFadeInAnimation` set. |
| `0x1c41fe20c`–`0x1c41fe218` | `SBLockScreenManager` asks its aggregate rule `shouldAutoUnlockForSource:`; its BOOL result is retained in `w22`. |
| `0x1c41fe278`–`0x1c41fe288` | The original wake path calls `turnOnScreenFullyWithBacklightSource:` independently of a true auto-unlock result. |
| `0x1c41fe400`–`0x1c41fe480` | With the existing turn-on-screen option and a false auto-unlock result, this branch returns without continuing to actual unlock. |
| `0x1c41fee94` | `-[SBLockScreenAutoUnlockAggregateRule shouldAutoUnlockForSource:]`; method-list entry `0x1c48b9f48`, encoding **`B20@0:8i16`**: BOOL result, signed 32-bit source. |

The existing SmartCover open event is not replaced, and the raw HES state,
close handling, observer notifications, workspace scheduling, system cover
preference, wake animation, and backlight path remain in the original code.

An independent local review in `log/host/hall-lockscreen-20261110/review/`
also traced manager initialization: its `+0x78` member is this aggregate rule.
The exit condition at `0x1c41fe400` is
`turnOnFirst && !(autoUnlock && canTurnOn)`. SmartCover's existing
`turnOnFirst=1` and the new `autoUnlock=0` take the no-unlock cleanup even if
the screen is already on or wake is disallowed. Actual unlock completion at
`0x1c41fe704` is not reached along this ordinary path.

## Change

`userland/nabu/src/setup_compat.c` is already injected into SpringBoard.
When both its existing `nabu-setup-compat=1` and `nabu-hall=1` switches are present,
it replaces only the aggregate auto-unlock rule. Source 3 returns false; every
other source calls the original implementation with its original arguments
and BOOL result. It does not simulate power-button events, change a passcode,
or add a direct backlight operation.

The host check exercises the actual production wrapper with Hall enabled and
disabled, both original BOOL results, SmartCover and other source values,
and signed argument boundaries. It also retains the 10 existing setup cases.
These 58 cases validate dispatch and call preservation; they do not execute
SpringBoard or prove display wake. Native compilation/signing and bootstrap
readback are separate checks, followed by a future device trial.

Remaining device acceptance: opening from a dark locked screen shows the lock
screen, swiping still unlocks normally, three cover cycles work, and the
power/volume buttons and touch remain usable. Special wake destinations such
as an already presented camera or remote alert are outside the observed
ordinary lock-screen path and have not been tested.

## Candidate result

Implementation commit `19074c2` passed all 58 host cases and native workflow
`42654906255` (Xcode 16.4, arm64 iOS 16.5, ad-hoc signature verification).
The 69,104-byte setup dylib and the unchanged input dylib were read back from
the new APFS container. The 68,034,560-byte candidate is
`artifacts/nabu-bootstrap-hall-lockscreen-20261110/bootstrap.apfs` and uses the
Hall02-qualified r3 kernel. Production boot-policy checks passed.

The original CI request `42653181611` never acquired a runner and was cancelled;
the successful run used the identical implementation commit. No device access,
log reservation, deployment or temporary boot was performed for this candidate.
Detailed receipts are under `log/host/hall-lockscreen-20261110/`, especially
`candidate-checks.json`, `download-review.json` and `continuation.json`.
