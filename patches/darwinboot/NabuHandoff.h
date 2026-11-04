// SPDX-License-Identifier: BSD-2-Clause-Patent
// Used only after AdtNode has validated the complete Apple tree.
typedef struct {
  BOOLEAN Enabled;
  BOOLEAN AutoMemory;
  UINTN DramBase;
  UINTN DramSize;
} NABU_HANDOFF;

STATIC BOOLEAN
NabuFindChosen (UINT8 *Data, UINTN Size, UINTN *Offset, UINTN Depth, NABU_HANDOFF *Out)
{
  UINTN Count, Children, Index, Length, Value, End;
  UINTN Base = MAX_UINTN, Bytes = MAX_UINTN;
  UINT32 Version = 0, Auto = 0;
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
  }
  for (Index = 0; Index < Children; ++Index) {
    if (!NabuFindChosen (Data, Size, Offset, Depth + 1, Out)) { return FALSE; }
  }
  return TRUE;
}

STATIC EFI_STATUS
NabuWriteHandoff (EFI_FILE_PROTOCOL *Root, KERNEL *Kernel, UINT64 Address,
                  UINT64 WindowSize, UINT64 ArgsAddress, UINT64 Video[6],
                  EFI_MEMORY_DESCRIPTOR *Map, UINTN MapSize, UINTN Stride,
                  CONST CHAR8 *CommandLine)
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
    "video_pa=%lx width=%lu height=%lu row=%lu depth=%lu\nargs=%a\n",
    READ_SYSREG (mpidr_el1), READ_SYSREG (cntfrq_el0), DarwinCurrentEl () >> 2,
    READ_SYSREG (id_aa64mmfr0_el1), READ_SYSREG (id_aa64pfr0_el1),
    Kernel->Base, Address, WindowSize, ArgsAddress, Address + Kernel->Entry - Kernel->Base,
    Video[0], Video[3], Video[4], Video[2], Video[5], CommandLine);
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
