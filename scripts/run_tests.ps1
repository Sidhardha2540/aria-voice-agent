param(
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"

if (Test-Path $venvPython) {
    $python = $venvPython
} else {
    $python = "python"
}

$args = @("-m", "pytest", "tests")
if ($Quiet) {
    $args += "-q"
} else {
    $args += @("-v", "--tb=short")
}

Write-Host "[tests] Using Python: $python"
& $python @args
