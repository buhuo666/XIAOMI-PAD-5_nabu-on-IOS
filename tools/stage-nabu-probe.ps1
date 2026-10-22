[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$ArtifactDirectory,
    [Parameter(Mandatory = $true)][string]$OutputDirectory,
    # Verified against run 39779752907, commit e535297, on 2026-10-22.
    [string]$ExpectedProbeSha256 = "3eb983d3682a3a34cf8e72f16fdf53ca7ade46f55426b443cc0059b38505c7d0"
)

$ErrorActionPreference = "Stop"
$source = [IO.Path]::GetFullPath($ArtifactDirectory)
$destination = [IO.Path]::GetFullPath($OutputDirectory)
if (Test-Path -LiteralPath $destination) { throw "Refusing to overwrite an existing kit: $destination" }
if ($ExpectedProbeSha256 -notmatch '^[0-9a-fA-F]{64}$') { throw "A SHA-256 digest is required." }
$probe = Join-Path $source "NabuProbe.efi"
$manifest = Get-Content -Raw -LiteralPath (Join-Path $source "manifest.json") | ConvertFrom-Json
$entry = $manifest.files.'NabuProbe.efi'
$hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $probe).Hash.ToLowerInvariant()
if ($hash -ne $ExpectedProbeSha256.ToLowerInvariant() -or
    $entry.sha256 -ne $hash -or (Get-Item -LiteralPath $probe).Length -ne $entry.bytes) {
    throw "Probe hash/size differs from the pinned digest or artifact manifest."
}
$image = [IO.File]::ReadAllBytes($probe)
if ($image.Length -lt 64 -or [BitConverter]::ToUInt16($image, 0) -ne 0x5a4d) {
    throw "Probe has no DOS/PE header."
}
$pe = [BitConverter]::ToInt32($image, 0x3c)
if ($pe -lt 0x40 -or $pe -gt $image.Length - 94 -or
    [BitConverter]::ToUInt32($image, $pe) -ne 0x4550 -or
    [BitConverter]::ToUInt16($image, $pe + 4) -ne 0xaa64 -or
    [BitConverter]::ToUInt16($image, $pe + 24) -ne 0x20b -or
    [BitConverter]::ToUInt16($image, $pe + 92) -ne 10) {
    throw "Probe is not a PE32+ ARM64 EFI application."
}
$efiDirectory = Join-Path $destination "EFI\NabuDiag"
New-Item -ItemType Directory -Path $efiDirectory -Force | Out-Null
Copy-Item -LiteralPath $probe -Destination (Join-Path $efiDirectory "NabuProbe.efi")
Copy-Item -LiteralPath (Join-Path $PSScriptRoot "collect-windows-arm-info.ps1") `
    -Destination (Join-Path $destination "collect-windows-arm-info.ps1")
Copy-Item -LiteralPath (Join-Path $PSScriptRoot "..\docs\existing-windows.md") `
    -Destination (Join-Path $destination "READ-ME-FIRST.md")
$provenance = [ordered]@{
    workflow_run = $manifest.workflow_run
    source_commit = $manifest.source_commit
    probe_sha256 = $hash
    probe_relative_path = "EFI/NabuDiag/NabuProbe.efi"
    hardware_tested = $false
    ready_to_boot_kernel = $false
    boot_entries_modified = $false
    limits = "Staged on the PC only. No kernel, default boot path, startup script or OS installer included."
}
[IO.File]::WriteAllText(
    (Join-Path $destination "provenance.json"),
    ($provenance | ConvertTo-Json -Depth 5) + "`n",
    [Text.UTF8Encoding]::new($false)
)
$stagedHash = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $efiDirectory "NabuProbe.efi")).Hash
if ($stagedHash.ToLowerInvariant() -ne $hash) { throw "Staged probe verification failed." }
Write-Output "Probe-only kit staged at $destination"
Write-Output "No device connection, EFI/BOOT file, startup.nsh, BCD update or partition operation was used."
