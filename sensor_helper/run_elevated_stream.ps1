# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

param(
    [Parameter(Mandatory = $true)]
    [string]$HelperDll,

    [Parameter(Mandatory = $true)]
    [string]$OutputPath,

    [Parameter(Mandatory = $true)]
    [string]$StopFile,

    [Parameter(Mandatory = $true)]
    [int]$OwnerPid
)

$arguments = @(
    ('"' + $HelperDll + '"'),
    '--compact-frequency',
    '--interval-ms',
    '2000',
    '--output',
    ('"' + $OutputPath + '"'),
    '--stop-file',
    ('"' + $StopFile + '"'),
    '--owner-pid',
    $OwnerPid.ToString()
)

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
