# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

param(
    [Parameter(Mandatory = $true)]
    [string]$HelperDll,

    [Parameter(Mandatory = $true)]
    [string]$OutputPath,

    [switch]$AllTelemetry,

    [switch]$CompactFrequency
)

$arguments = @(
    ('"' + $HelperDll + '"'),
    '--once',
    '--output',
    ('"' + $OutputPath + '"')
)

# Inventory mode is still read-only; it simply asks LHM to open GPU and memory
# hardware groups in addition to the CPU so we can record stable identifiers.
if ($AllTelemetry) {
    $arguments += '--all-telemetry'
}

if ($CompactFrequency) {
    $arguments += '--compact-frequency'
}

# Keep a sidecar of the exact wrapper decision. It contains no sensor values,
# but makes future "did elevation drop the flag?" failures diagnosable.
if ($AllTelemetry) {
    Set-Content -LiteralPath ($OutputPath + '.launcher.txt') -Value ($arguments -join ' ') -Encoding UTF8
}

try {
    $process = Start-Process `
        -FilePath 'dotnet.exe' `
        -ArgumentList $arguments `
        -Verb RunAs `
        -Wait `
        -PassThru `
        -WindowStyle Hidden
    exit $process.ExitCode
}
catch {
    Write-Error $_.Exception.Message
    exit 1223
}
