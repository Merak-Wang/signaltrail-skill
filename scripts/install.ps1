param(
    [switch]$Editable,
    [switch]$Dev
)

$installerArgs = @()
if ($Editable) { $installerArgs += "--editable" }
if ($Dev) { $installerArgs += "--dev" }
& python (Join-Path $PSScriptRoot "install.py") @installerArgs
exit $LASTEXITCODE
