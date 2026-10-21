param(
    [switch]$Editable,
    [switch]$Dev
)

$ErrorActionPreference = "Stop"
$skillDir = Split-Path $PSScriptRoot -Parent
$hermesHome = if ($env:HERMES_HOME) {
    [IO.Path]::GetFullPath($env:HERMES_HOME)
} else {
    [IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA "hermes"))
}
$skillsRoot = [IO.Path]::GetFullPath((Join-Path $hermesHome "skills"))
$targetDir = [IO.Path]::GetFullPath((Join-Path $skillsRoot "research\signaltrail"))
if (-not $targetDir.StartsWith($skillsRoot, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to synchronize outside the Hermes skills directory: $targetDir"
}
New-Item -ItemType Directory -Force -Path $targetDir | Out-Null

$sameDirectory = [String]::Equals(
    [IO.Path]::GetFullPath($skillDir).TrimEnd([IO.Path]::DirectorySeparatorChar),
    $targetDir.TrimEnd([IO.Path]::DirectorySeparatorChar),
    [StringComparison]::OrdinalIgnoreCase
)
$excludedDirs = @(
    ".agents", ".code-review-graph", ".codex", ".git", ".github", ".idea",
    ".playwright-cli", ".pytest_cache", ".ruff_cache", ".vscode", "__pycache__",
    ".venv", "venv", "env",
    "blob-report", "build", "dist", "data", "daily-intelligence", "daily-intel-data",
    "browser-profile", "browser-profiles", "edge-profile", "htmlcov", "output",
    "playwright-report", "raw_html", "screenshots", "test-results", "tmp",
    "daily_intelligence_skill.egg-info", "signaltrail_skill.egg-info", "skills"
)
$excludedFiles = @(".env", "*.cookies.json", "*.har", "*.storage-state.json", "brief*.json")
if (-not $sameDirectory) {
    & robocopy $skillDir $targetDir /E /R:1 /W:1 /NFL /NDL /NJH /NJS /NP `
        /XD $excludedDirs /XF $excludedFiles
    if ($LASTEXITCODE -ge 8) {
        throw "Skill synchronization failed with robocopy exit code $LASTEXITCODE"
    }
}

$packageRoot = if ($Editable) { $skillDir } else { $targetDir }
$package = if ($Dev) { "${packageRoot}[dev]" } else { $packageRoot }
$pipArgs = @("-m", "pip", "install", "-e")
$pipArgs += $package
& python @pipArgs
if ($LASTEXITCODE -ne 0) {
    throw "Package installation failed with exit code $LASTEXITCODE"
}
Write-Host "Synchronized SignalTrail skill: $targetDir"
Write-Host "Installed package. Windows collection uses system Microsoft Edge; no bundled browser download is required."
Write-Host "Run: signaltrail --help"
