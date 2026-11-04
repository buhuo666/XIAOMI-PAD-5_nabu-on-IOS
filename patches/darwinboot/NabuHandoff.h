// SPDX-License-Identifier: BSD-2-Clause-Patent
// Used only after AdtNode has validated the complete Apple tree.

// Existing assembly and arm_init checkpoints in the pinned 8796 kernel.
#define NABU_CHECKPOINT_VALID(N) (((N) >= 1 && (N) <= 5) || \
                                ((N) >= 10 && (N) <= 21) || \
                                ((N) >= 30 && (N) <= 35) || \
                                ((N) >= 40 && (N) <= 44))
typedef struct {
  BOOLEAN Enabled;
  BOOLEAN AutoMemory;
  UINTN DramBase;
  UINTN DramSize;
  UINT32 Checkpoint;
  UINT64 ReportAddress;
} NABU_HANDOFF;

// Direct framebuffer text; safe after ExitBootServices because it calls no
// firmware service and allocates nothing. Three rows stay visible mid-screen.
STATIC VOID
NabuDrawPhase (UINT64 Video[6], CONST CHAR16 *Text, UINTN Row)
{
  volatile UINT32 *Fb = (volatile UINT32 *)(UINTN)Video[0];
  UINTN X = 0, Y, Index, Gx, Gy, Dx, Dy;
  UINT64 Glyph, Bits;
  CHAR16 Ch;
  if (Video[0] == 0 || Video[3] < 24 || Video[4] < 224 || Row >= 3) { return; }
  Y = Video[4] / 2 + Row * 56;
  if (Y + 56 > Video[4]) { return; }
  for (Index = 0; Text[Index] != 0; ++Index) {
    Ch = Text[Index];
    if (Ch < 32 || Ch > 126) { continue; }
    if (X + 24 > Video[3]) { break; }
    Glyph = mDiagFont[Ch - 32];
    for (Gy = 0; Gy < 56; ++Gy) {
      for (Gx = 0; Gx < 24; ++Gx) { Fb[(Y + Gy) * (Video[2] / 4) + X + Gx] = 0xff000000; }
    }
    for (Gy = 0; Gy < 12; ++Gy) {
      Bits = Gy < 6 ? (Glyph >> 32) >> (Gy * 5) : (Glyph & 0xffffffffULL) >> ((Gy - 6) * 5);
      for (Gx = 0; Gx < 5; ++Gx) {
        if ((Bits >> Gx) & 1) {
          for (Dy = 0; Dy < 4; ++Dy) {
            for (Dx = 0; Dx < 4; ++Dx) { Fb[(Y + Gy * 4 + Dy) * (Video[2] / 4) + X + Gx * 4 + Dx] = 0xffffffff; }
          }
        }
      }
    }
    X += 24;
  }
  __asm__ volatile ("dsb sy" ::: "memory");
}

STATIC BOOLEAN
NabuFindChosen (UINT8 *Data, UINTN Size, UINTN *Offset, UINTN Depth, NABU_HANDOFF *Out)
{
  UINTN Count, Children, Index, Length, Value, End;
  UINTN Base = MAX_UINTN, Bytes = MAX_UINTN;
  UINT32 Version = 0, Auto = 0, Checkpoint = 0;
  BOOLEAN Chosen = FALSE;
  CONST CHAR8 *Key;
  if ((Depth > 32) || (*Offset > Size) || (Size - *Offset < 8)) { return FALSE; }
  Count = U32 (Data + *Offset);
  Children = U32 (Data + *Offset + 4);
  *Offset += 8;
  for (Index = 0; Index < Count; ++Index) {
    if (*Offset > Size || Size - *Offset < 36) { return FALSE; }
    Key = (CONST CHAR8 *)(Data + *Offset);
    Length = U32 (Data + *Offset + 32);
    Value = *Offset + 36;
    if (Length > Size - Value) { return FALSE; }
    End = ALIGN_VALUE (Value + Length, 4);
    if (End > Size) { return FALSE; }
    if (AsciiStrCmp (Key, "name") == 0 && Length == 7 && CompareMem (Data + Value, "chosen", 7) == 0) { Chosen = TRUE; }
    if (AsciiStrCmp (Key, "nabu-handoff-version") == 0 && Length == 4) { Version = U32 (Data + Value); }
    if (AsciiStrCmp (Key, "darwinboot-auto-memory") == 0 && Length == 4) { Auto = U32 (Data + Value); }
    if (AsciiStrCmp (Key, "nabu-kernel-checkpoint") == 0) {
      if (Length != 4 || (U32 (Data + Value) != 0 && !NABU_CHECKPOINT_VALID (U32 (Data + Value)))) { return FALSE; }
      Checkpoint = U32 (Data + Value);
    }
    if (AsciiStrCmp (Key, "dram-base") == 0 && Length == 8) { Base = Value; }
    if (AsciiStrCmp (Key, "dram-size") == 0 && Length == 8) { Bytes = Value; }
    *Offset = End;
  }
  if (Depth == 1 && Chosen && Version != 0) {
    if (Out->Enabled || Version != 1 || Auto != 1 || Base == MAX_UINTN || Bytes == MAX_UINTN ||
        U64 (Data + Base) != 0 || U64 (Data + Bytes) != 0) { return FALSE; }
    Out->Enabled = TRUE;
    Out->AutoMemory = TRUE;
    Out->DramBase = Base;
    Out->DramSize = Bytes;
    Out->Checkpoint = Checkpoint;
  }
  for (Index = 0; Index < Children; ++Index) {
    if (!NabuFindChosen (Data, Size, Offset, Depth + 1, Out)) { return FALSE; }
  }
  return TRUE;
}

#include "NabuKernelReportBlob.h"

// Bind only the kernel's explicit, unique and previously unset callback slot.
// The report is copied into owned RAM and never tries to re-enter UEFI.
STATIC EFI_STATUS
NabuInstallKernelReport (KERNEL *Kernel, UINT64 Address, UINT64 ReportAddress,
                         UINT32 Checkpoint, UINT64 Video[6])
{
  UINTN Index, Offset, Matches = 0;
  UINT8 *Data;
  UINT64 *Slot = NULL;
  UINT64 *Config;
  if (!NABU_CHECKPOINT_VALID (Checkpoint) || (ReportAddress & (SIZE_16KB - 1)) != 0) {
    return EFI_INVALID_PARAMETER;
  }
  for (Index = 0; Index < Kernel->Count; ++Index) {
    Data = (UINT8 *)(UINTN)(Address + Kernel->Segments[Index].Address - Kernel->Base);
    for (Offset = 0; Offset + 32 <= Kernel->Segments[Index].FileSize; Offset += 8) {
      if (CompareMem (Data + Offset, "XNULDRST", 8) != 0) { continue; }
      if (U64 (Data + Offset + 8) != 0 || U64 (Data + Offset + 16) != 0 ||
          U64 (Data + Offset + 24) != 0) { return EFI_COMPROMISED_DATA; }
      Slot = (UINT64 *)(Data + Offset);
      ++Matches;
    }
  }
  if (Matches != 1) { return EFI_COMPROMISED_DATA; }
  CopyMem ((VOID *)(UINTN)ReportAddress, mNabuKernelReport, sizeof (mNabuKernelReport));
  Config = (UINT64 *)(UINTN)(ReportAddress + NABU_KERNEL_REPORT_CONFIG);
  CopyMem (Config + 8, Video, 6 * sizeof (UINT64));
  CopyMem (Config + 14, mDiagFont, 95 * sizeof (UINT64));
  Slot[1] = ReportAddress;
  Slot[2] = Checkpoint;
  Slot[3] = Address - Kernel->Base;
  return EFI_SUCCESS;
}

STATIC EFI_STATUS
NabuWriteHandoff (EFI_FILE_PROTOCOL *Root, KERNEL *Kernel, UINT64 Address,
                  UINT64 WindowSize, UINT64 ArgsAddress, UINT64 Video[6],
                  EFI_MEMORY_DESCRIPTOR *Map, UINTN MapSize, UINTN Stride,
                  CONST CHAR8 *CommandLine, CONST NABU_HANDOFF *Nabu)
{
  EFI_FILE_PROTOCOL *File;
  EFI_STATUS Status;
  CHAR16 Path[100];
  CHAR8 Line[1536];
  UINTN Length, Written, Offset;
  EFI_MEMORY_DESCRIPTOR *D;
  UnicodeSPrint (Path, sizeof (Path), L"\\EFI\\Nabu16\\handoff-%lx.txt", READ_SYSREG (cntvct_el0));
  Status = Root->Open (Root, &File, Path, EFI_FILE_MODE_CREATE | EFI_FILE_MODE_READ | EFI_FILE_MODE_WRITE, 0);
  if (EFI_ERROR (Status)) { return Status; }
  Length = AsciiSPrint (Line, sizeof (Line),
    "NABU8796: pre-ExitBootServices evidence; kernel execution not yet established\n"
    "MPIDR=%lx CNTFRQ=%lu EL=%lu MMFR0=%lx PFR0=%lx\n"
    "kernel_va=%lx allocated_pa=%lx allocated_bytes=%lx args_pa=%lx entry_pa=%lx\n"
    "video_pa=%lx width=%lu height=%lu row=%lu depth=%lu\nargs=%a\n"
    "kernel_checkpoint=%u callback_pa=%lx (diagnostic stop, not a full boot)\n",
    READ_SYSREG (mpidr_el1), READ_SYSREG (cntfrq_el0), DarwinCurrentEl () >> 2,
    READ_SYSREG (id_aa64mmfr0_el1), READ_SYSREG (id_aa64pfr0_el1),
    Kernel->Base, Address, WindowSize, ArgsAddress, Address + Kernel->Entry - Kernel->Base,
    Video[0], Video[3], Video[4], Video[2], Video[5], CommandLine, Nabu->Checkpoint, Nabu->ReportAddress);
  Written = Length;
  Status = File->Write (File, &Written, Line);
  if (!EFI_ERROR (Status) && Written != Length) { Status = EFI_DEVICE_ERROR; }
  for (Offset = 0; !EFI_ERROR (Status) && Offset + Stride <= MapSize; Offset += Stride) {
    D = (EFI_MEMORY_DESCRIPTOR *)((UINT8 *)Map + Offset);
    Length = AsciiSPrint (Line, sizeof (Line), "map type=%u base=%lx pages=%lx attr=%lx\n",
                          D->Type, D->PhysicalStart, D->NumberOfPages, D->Attribute);
    Written = Length;
    Status = File->Write (File, &Written, Line);
    if (!EFI_ERROR (Status) && Written != Length) { Status = EFI_DEVICE_ERROR; }
  }
  if (!EFI_ERROR (Status)) { Status = File->Flush (File); }
  File->Close (File);
  return Status;
}
