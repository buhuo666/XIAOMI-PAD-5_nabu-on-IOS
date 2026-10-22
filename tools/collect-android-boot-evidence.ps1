[CmdletBinding()]
param(
    [string]$AdbPath = "adb",
    [string]$DeviceSerial,
    [string]$OutputPath = "out/android-boot-evidence.json"
)

$ErrorActionPreference = "Stop"
$target = [IO.Path]::GetFullPath($OutputPath)
if (Test-Path -LiteralPath $target) { throw "Refusing to overwrite an existing report: $target" }
$adbExecutable = (Get-Command -Name $AdbPath -CommandType Application -ErrorAction Stop).Source
$deviceLines = & $adbExecutable devices 2>&1
if ($LASTEXITCODE -ne 0) { throw "ADB device discovery failed." }
$authorized = @(
    foreach ($line in $deviceLines) {
        if ([string]$line -match '^(\S+)\s+device\s*$') { $Matches[1] }
    }
)
if ($DeviceSerial) {
    if ($DeviceSerial -notin $authorized) { throw "The selected device is not authorized." }
    $selectedDevice = $DeviceSerial
} elseif ($authorized.Count -eq 1) {
    $selectedDevice = $authorized[0]
} else {
    throw "Exactly one authorized ADB device is required, or select one with -DeviceSerial."
}

function Read-Device {
    param([string[]]$Arguments)
    $text = & $adbExecutable -s $selectedDevice shell @Arguments 2>&1
    $exitCode = $LASTEXITCODE
    [ordered]@{
        exit_code = $exitCode
        text = (($text | ForEach-Object { [string]$_ }) -join "`n").Trim().Replace([char]0, "|")
    }
}

$identity = Read-Device -Arguments @("getprop", "ro.product.device")
if ($identity.exit_code -ne 0 -or $identity.text -ne "nabu") {
    throw "The connected device did not report nabu. No report was written."
}

# Fixed reads only. No su, root, reboot, install, mount, block-device contents,
# filesystem traversal, device-tree binary dump, or persistent-device writes.
$observations = [ordered]@{}
$observations["kernel_release"] = Read-Device -Arguments @("uname", "-r")
foreach ($key in @(
    "ro.boot.slot_suffix", "ro.boot.flash.locked", "ro.boot.verifiedbootstate",
    "ro.boot.bootdevice", "ro.build.version.release"
)) {
    $observations[$key] = Read-Device -Arguments @("getprop", $key)
}
foreach ($path in @(
    "/sys/devices/soc0/soc_id", "/sys/devices/soc0/revision",
    "/sys/devices/system/cpu/present", "/sys/devices/system/cpu/online",
    "/sys/firmware/devicetree/base/model",
    "/sys/firmware/devicetree/base/compatible",
    "/sys/class/drm/card0-DSI-1/status", "/sys/class/drm/card0-DSI-1/enabled",
    "/sys/class/drm/card0-DSI-1/modes"
)) {
    $observations[$path] = Read-Device -Arguments @("cat", $path)
}

$links = Read-Device -Arguments @("ls", "-l", "/dev/block/by-name")
if ($links.exit_code -ne 0) { throw "Cannot read partition names. No report was written." }
$partitionMap = @{}
foreach ($line in ($links.text -split "`n")) {
    if ($line -match '\s([A-Za-z0-9_-]+)\s+->\s+/dev/block/(sd[a-z]+[0-9]*)\s*$') {
        $partitionMap[$Matches[1]] = $Matches[2]
    }
}
$selectedNames = @(
    "mindowsesp", "mindowswin", "mindowsdat", "userdata", "cust", "rescue", "switch",
    "boot_a", "boot_b", "vendor_boot_a", "vendor_boot_b", "dtbo_a", "dtbo_b",
    "uefivarstore"
)
$partitions = [ordered]@{}
$diskNames = @{}
foreach ($name in $selectedNames) {
    if (-not $partitionMap.ContainsKey($name)) { continue }
    $block = $partitionMap[$name]
    $entry = [ordered]@{ block = $block }
    foreach ($field in @("start", "size")) {
        $read = Read-Device -Arguments @("cat", "/sys/class/block/$block/$field")
        $entry[$field] = $read
        if ($read.exit_code -eq 0 -and $read.text -match '^\d+$') {
            $entry[$field + "_sectors_512"] = [uint64]$read.text
            $entry[$field + "_bytes"] = [uint64]$read.text * [uint64]512
        }
    }
    $partitions[$name] = $entry
    $diskNames[($block -replace '\d+$', '')] = $true
}
$disks = [ordered]@{}
foreach ($disk in @($diskNames.Keys | Sort-Object)) {
    $entry = [ordered]@{}
    foreach ($field in @("size", "queue/logical_block_size", "queue/physical_block_size")) {
        $entry[$field] = Read-Device -Arguments @("cat", "/sys/class/block/$disk/$field")
    }
    $disks[$disk] = $entry
}
$report = [ordered]@{
    report_version = 1
    collected_at = (Get-Date).ToString("o")
    transport = "authorized ADB; fixed read-only hardware and partition-metadata queries"
    nabu_identity_reported = $true
    observations = $observations
    selected_partitions = $partitions
    disks = $disks
    mindows_partition_names_present = @(
        @("mindowsesp", "mindowswin", "mindowsdat") |
            Where-Object { $partitionMap.ContainsKey($_) }
    )
    protected_partition_names = $selectedNames
    partition_table_backup_created = $false
    partition_contents_read = $false
    uefi_source_verified = $false
    uefi_memory_map_verified = $false
    ready_to_boot = $false
    limitations = @(
        "Partition names do not establish filesystem health, free space, or the installed firmware.",
        "Linux sysfs start and size use 512-byte sectors, independently of logical block size.",
        "Denied reads are retained with their exit status; no privilege escalation is attempted.",
        "Android display modes do not establish UEFI GOP base, stride, format or active mode.",
        "Existing Windows, ESP, Android, boot and firmware partitions must be preserved.",
        "No serial, personal files, GPT GUIDs, partition contents or NVRAM data are collected."
    )
}
$parent = Split-Path -Parent $target
if (-not (Test-Path -LiteralPath $parent)) {
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
}
$bytes = [Text.Encoding]::UTF8.GetBytes(($report | ConvertTo-Json -Depth 10) + "`n")
$stream = [IO.File]::Open($target, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
try { $stream.Write($bytes, 0, $bytes.Length) } finally { $stream.Dispose() }
Write-Output "Read-only boot evidence written to $target"
Write-Output ("Mindows partition names: " + ($report.mindows_partition_names_present -join ", "))
Write-Output "No reboot, privilege escalation, partition-content read or device write was performed."
