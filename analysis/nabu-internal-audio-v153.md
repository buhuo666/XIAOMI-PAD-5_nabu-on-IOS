# Nabu native output and microphone control, run153

The run152 user confirmed that all four speakers play normal application audio.
At maximum system volume, perceived loudness was about10% of Android. Recovered
logs contain15,562,624 native frames,42,004 DSP completions and no dropped frames
or underruns. The9,361,849-byte continuous log prefix and64MiB slot were backed
up and cleared; APFS boot count is122. A committed shutdown-log header is absent.

The amplifier still used the run151 fixed -24dB trial attenuation. The original
Android overlay sets all four Digital PCM Volume controls to817. Vendor
cs35l41_set_vol maps817 to register code0, meaning0dB. Commit924dc6f restores
that gain and passed CI42493098800; it has not been booted independently.

This candidate also applies the existing native HAL volume ioctl to the actual
PCM feeder. The inherited hakios audio device stores attenuation/mute for its
physical sink; run152's Nabu sink copied samples without consuming that setting.
The feeder now reads it outside the audio writer lock and applies a Q24 gain
when filling DSP periods. Hardware Protection/calibration remains in use.

Microphone control uses a second GLINK channel, IPCRTR, within the existing
host2/APR FIFO owner. QRTR discovers service0x301/version1/instance0, selects
instance0 with ADSP MASTER mode2, then holds the POWER ACTIVE2 lease. Normal
shutdown stops codec register access before POWER INACTIVE1 and DEL_CLIENT.
The ath10k QRTR/QMI transport is unchanged.

The codec path resolves original bobc1 and lnbclka2 resources, retains the
original fixed1.8V S4 supply, handles GPIO143 reset, and runs serialized NGD
register transactions. It queries the Tavil PGD/IFD elemental addresses, uses
page-register accesses, executes the vendor digital bring-up, and reads the
chip identity. The original driver supports a register RX path, but Nabu's
original configuration uses BAM; this register mode still needs real hardware
evidence. A failed microphone control path is reported independently and the
normal speaker stream continues.

Host checks cover shared APR/IPCRTR ownership, QRTR1/3, exact SELECT/POWER wire
bytes, fragments, transaction matching and lease shutdown; NGD old/new register
banks, capability exchange, retained logical address, page switching, original
bring-up writes, identity responses and a missing RX timeout. ASan/UBSan and
the ARM64 NabuAdsp compile passed. These checks do not prove physical recording.

Still required: real NGD/codec control confirmation, Tavil analog bias/ADC/DEC
configuration, SLIM capture channel scheduling, AFE/ADM/ASM capture buffers and
a native input provider. No silent placeholder is presented as a working mic.
User testing remains self-directed; this candidate generates no automatic tone
and imposes no playback duration limit.
