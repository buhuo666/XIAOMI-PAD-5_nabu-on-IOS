# GPU224 shipped DarwinBoot handoff investigation

The input is the 37,888-byte DarwinBoot.efi distributed with GPU224, copied from
the frozen deployment kit. It contains no tablet personalization. Its existing
build receipt records SHA-256
`dbba8f6ebe0df006878684a4227c911d568ce378b1bd3b3b0b65dc862131f8c5`.

Questions: which ADT properties enable NabuFindChosen; whether handoff files
are written before or after kernel callbacks; whether nonzero on-disk DRAM
properties can pass the supplied loader; whether missing version and memory
properties reproduce disabled callbacks. The recovered fallback is 256MiB;
the reported 1GiB is therefore not evidence of that default being used.

Ghidra recovers searchable C and assembly on GitHub Actions. An independent
Unicorn replay executes the input PE's NabuFindChosen bytes using synthetic
ADTs only. Function RVA 0x3454 comes from its retained v24b link map, and is
cross-checked with the recovered function. It calls only PE code in the same
mapped image. No firmware services, real memory map, storage, device or kernel
are executed. The replay cannot establish which bytes the other tablet loaded.

Source workflow base: GPU224 commit a714855. All outputs remain diagnostic
evidence, not a repaired or newly built kernel/EFI.
