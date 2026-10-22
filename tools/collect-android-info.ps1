[CmdletBinding()]
param(
    [string]$AdbPath = "adb",
    [string]$DeviceSerial,
    [string]$OutputPath = "out/android-device-report.json"
)

$ErrorActionPreference = "Stop"
$adbCommand = Get-Command -Name $AdbPath -CommandType Application -ErrorAction Stop
$adbExecutable = $adbCommand.Source
$deviceLines = & $adbExecutable devices 2>&1
if ($LASTEXITCODE -ne 0) { throw "ADB device discovery failed." }
$authorized = @(
    foreach ($line in $deviceLines) {
        if ([string]$line -match '^(\S+)\s+device\s*$') { $Matches[1] }
    }
)
if ($DeviceSerial) {
    if ($DeviceSerial -notin $authorized) {
        throw "The selected device is not connected and authorized. No device changes were made."
    }
    $selectedDevice = $DeviceSerial
} elseif ($authorized.Count -eq 1) {
    $selectedDevice = $authorized[0]
} else {
    throw "Exactly one authorized ADB device is required, or select one with -DeviceSerial. No device changes were made."
}

function Read-Device {
    param([string[]]$Arguments)
    $text = & $adbExecutable -s $selectedDevice shell @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) { return $null }
    return (($text | ForEach-Object { [string]$_ }) -join "`n").Trim()
}

# Only fixed getprop/cat reads are issued. No root, reboot, fastboot, writes,
# partition commands, package installation, or full personal-data dumps.
$properties = [ordered]@{}
foreach ($key in @(
    "ro.product.device", "ro.product.vendor.device", "ro.board.platform",
    "ro.product.cpu.abi", "ro.build.version.release",
    "ro.boot.flash.locked", "ro.boot.verifiedbootstate",
    "ro.boot.vbmeta.device_state"
)) {
    $properties[$key] = Read-Device -Arguments @("getprop", $key)
}
$meminfo = Read-Device -Arguments @("cat", "/proc/meminfo")
if (-not $meminfo) { throw "Cannot read /proc/meminfo; no report was produced." }
$memory = [ordered]@{}
foreach ($key in @("MemTotal", "MemAvailable", "SwapTotal", "SwapFree")) {
    $pattern = '(?m)^' + [regex]::Escape($key) + ':\s+(\d+)\s+kB\s*$'
    $match = [regex]::Match($meminfo, $pattern)
    if ($match.Success) { $memory[$key + "_KiB"] = [uint64]$match.Groups[1].Value }
}
if (-not $memory.Contains("MemTotal_KiB")) { throw "Invalid MemTotal in the device report." }
$identityMatches = $properties["ro.product.device"] -eq "nabu" -or
    $properties["ro.product.vendor.device"] -eq "nabu"
$report = [ordered]@{
    report_version = 1
    collected_at = (Get-Date).ToString("o")
    transport = "authorized ADB; fixed read-only queries"
    nabu_identity_reported = $identityMatches
    properties = $properties
    memory = $memory
    android_memtotal_bytes = $memory["MemTotal_KiB"] * 1024
    physical_dram_capacity_verified = $false
    uefi_memory_map_verified = $false
    ready_to_boot = $false
    limitations = @(
        "Android MemTotal excludes reserved regions and does not establish physical DRAM capacity.",
        "Swap/RAM extension is listed separately; it is not physical RAM.",
        "Android properties do not establish the UEFI GOP, memory map or bootloader compatibility.",
        "Device serial and personal data are omitted. Review reports before publishing."
    )
}
$target = [IO.Path]::GetFullPath($OutputPath)
if (Test-Path -LiteralPath $target) { throw "Refusing to overwrite an existing report: $target" }
$parent = Split-Path -Parent $target
if (-not (Test-Path -LiteralPath $parent)) {
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
}
$bytes = [Text.Encoding]::UTF8.GetBytes(($report | ConvertTo-Json -Depth 6) + "`n")
$stream = [IO.File]::Open($target, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
try { $stream.Write($bytes, 0, $bytes.Length) } finally { $stream.Dispose() }
Write-Output "Read-only report written to $target"
Write-Output "Android MemTotal: $($memory['MemTotal_KiB']) KiB; reported nabu identity: $identityMatches"
