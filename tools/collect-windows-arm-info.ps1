[CmdletBinding()]
param(
    [string]$OutputPath = "windows-arm-device-report.json"
)

$ErrorActionPreference = "Stop"
$nativeArchitecture = $env:PROCESSOR_ARCHITEW6432
if (-not $nativeArchitecture) { $nativeArchitecture = $env:PROCESSOR_ARCHITECTURE }
if ($env:OS -ne "Windows_NT" -or $nativeArchitecture -ne "ARM64") {
    throw "Run this script inside Windows on the ARM64 tablet, not on the connected x64 PC."
}
$target = [IO.Path]::GetFullPath($OutputPath)
if (Test-Path -LiteralPath $target) { throw "Refusing to overwrite an existing report: $target" }

function Read-Observation {
    param([scriptblock]$Read)
    try {
        $data = @(& $Read)
        [ordered]@{ available = $true; data = $data }
    } catch {
        [ordered]@{ available = $false; error_id = $_.FullyQualifiedErrorId }
    }
}

# Queries only: no drive-letter assignment, mounting, BCD edits, firmware
# changes, raw-disk access, volume labels, computer names, serials or unique IDs.
$report = [ordered]@{
    report_version = 1
    collected_at = (Get-Date).ToString("o")
    native_architecture = $nativeArchitecture
    computer_system = Read-Observation {
        Get-CimInstance Win32_ComputerSystem |
            Select-Object Manufacturer, Model, SystemType, TotalPhysicalMemory
    }
    operating_system = Read-Observation {
        Get-CimInstance Win32_OperatingSystem |
            Select-Object Caption, Version, BuildNumber, OSArchitecture
    }
    bios = Read-Observation {
        Get-CimInstance Win32_BIOS |
            Select-Object Manufacturer, SMBIOSBIOSVersion, ReleaseDate
    }
    secure_boot = Read-Observation {
        Confirm-SecureBootUEFI
    }
    disks = Read-Observation {
        Get-Disk | Sort-Object Number |
            Select-Object Number, FriendlyName, BusType, PartitionStyle, Size,
                LogicalSectorSize, PhysicalSectorSize, IsBoot, IsSystem
    }
    partitions = Read-Observation {
        Get-Partition | Sort-Object DiskNumber, PartitionNumber |
            Select-Object DiskNumber, PartitionNumber, Type, GptType, Size,
                Offset, DriveLetter, IsBoot, IsSystem, IsHidden, IsReadOnly
    }
    volumes = Read-Observation {
        Get-Volume | Sort-Object DriveLetter |
            Select-Object DriveLetter, FileSystemType, HealthStatus, Size, SizeRemaining
    }
    partition_table_backup_created = $false
    uefi_memory_map_verified = $false
    ready_to_boot = $false
    limitations = @(
        "Run on the tablet itself; an Android USB connection does not expose its running Windows.",
        "ARM64 architecture alone is not proof of the nabu device identity.",
        "SMBIOS reports the installed firmware identity, not a verified firmware-image hash.",
        "Windows usable memory does not establish the UEFI pre-boot memory map.",
        "A GPT type GUID is a standard type, not the unique partition GUID.",
        "No reboot, BCD change, ESP mount, partition modification or device deployment is performed."
    )
}
$parent = Split-Path -Parent $target
if (-not (Test-Path -LiteralPath $parent)) {
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
}
$bytes = [Text.Encoding]::UTF8.GetBytes(($report | ConvertTo-Json -Depth 10) + "`n")
$stream = [IO.File]::Open($target, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
try { $stream.Write($bytes, 0, $bytes.Length) } finally { $stream.Dispose() }
Write-Output "Read-only Windows ARM report written to $target"
