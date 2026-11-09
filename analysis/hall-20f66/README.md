# nabu Hall / Smart Cover interface (20F66)

Scope: only the real GPIO9 lid switch, close-to-lock and open-to-wake. Android
capture `log/host/hall-20261109/android/hall-edges.txt` contains three SW_LID 1/0
cycles, confirmed working by the user in the pasted continuation. GPIO83 is a
separate SW_TABLET_MODE switch; it is not used for this lid implementation.

## Original binary evidence

`inspect_hall.py` reads the locally extracted, unmodified 20F66 backboardd,
decodes Mach-O chained pointers and Objective-C method metadata, and disassembles
bounded functions with Capstone. It does not execute Apple code. The connected
REA server has no usable native provider on this host; these are ordinary local
binary observations, not REA Evidence or runtime observations.

Original file: `log/host/hall-20261109/original/usr/libexec/backboardd`, from the
already retained 20F66 OS image. Saved disassemblies are beside this README but
ignored by Git. The unrelated SmartCoverServiceFilter plugin handles accessory
touch/keyboard filtering and is not the lid-switch event producer.

| Address | Observation |
| --- | --- |
| `0x100062f70`, block `0x100062fb0` | `+[BKSmartCoverHIDEventProcessor isSmartCoverSupported]` caches `BSSystemHasCapability("hall-effect-sensor")`. |
| `0x1000621c4` | `initWithContext:` queries keyboard HES usages 1, 2, 3, 4 once and passes supported/disengaged masks to the initializer. |
| `0x100062080` | `_currentMaskForUsage:HIDSystem:mask:maskIfEngaged:` creates keyboard events on vendor page `0xff09`. Usage 1 contributes mask 1. |
| `0x100061d9c` | `initWithSupportedHES:disengagedHES:attached:unknownState:` encoding `@40@0:8Q16Q24B32B36`. One HES uses that same mask as the required open mask. |
| `0x1000624e4`–`0x100062530` | `processEvent:sender:dispatcher:` reads keyboard page `0x30000`, usage `0x30001`, down `0x30002`; accepts page `0xff09`. |
| `0x1000624f8`–`0x100062500` | Drops events when `sensorsRequiredForOpenState` is zero; log at `0x1000cce11` says no HES sensors. |
| `0x100062784`–`0x1000627c4` | Usage 1/down 1 calls `_smartCoverSensorsDidEngage:`; down 0 calls `_smartCoverSensorsDidDisengage:`. Attaches resulting state with `BKSHIDEventSetSmartCoverState`. |
| `0x1000623c4` | Engaging the last disengaged sensor sets internal state 2 and returns event state 3 (closed). Duplicate stable closed returns zero. |
| `0x100062400` | Disengaging the required sensor sets internal state 1 and returns event state 1 (open). Duplicate stable open returns zero. |

Method encoding of `isSmartCoverSupported` is `B16@0:8`. The page is a vendor
keyboard page, not the ordinary Consumer Power button. No state toggling or
Power-button emulation is needed. Event metadata state values differ from the
processor's internal enum; the bridge sends raw HES down/up and leaves both
enums and observer delivery to the original processor.

The adapter changes only these two processor methods and only with
`nabu-input=1 nabu-hall=1` plus a real GPIO sample already published. The original
initializer gets one sensor and its current level; the original event processor,
system display policy and framebuffer power request remain in use. This is an
explicit nabu board adaptation, not a claim that an Apple Hall device exists.

## Hardware evidence

Android DT `soc/gpio_keys/hall_key`: GPIO phandle 0x38, pin 9, active-low 1,
input type 5 (EV_SW), code 0 (SW_LID), debounce 15 ms and wakeup flag. The
`gpio_keys/pinctrl-0` phandle 0x68c configures the volume-up PMIC GPIO6, not Hall.
The existing SM8150 pinctrl reference maps GPIO9 to NORTH. NORTH base plus
9*0x1000 gives `0x03109000`, input bit 0 at offset 4.

Host tests verify production debounce and extracted bridge dispatch functions.
They do not prove device wake. This implementation polls while XNU is running;
SoC suspend interrupt routing is outside this display-off task.
