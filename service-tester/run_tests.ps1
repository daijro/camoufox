<#
.SYNOPSIS
    Windows equivalent of run_tests.sh for Camoufox service tests.

.DESCRIPTION
    Orchestrates two test phases against locally compiled and/or fetched
    Camoufox binaries on Windows, mirroring the behaviour of run_tests.sh.

.PARAMETER BrowserVersion
    Camoufox version specifier (default: official/stable)
    e.g. official/prerelease/146.0.1-beta.50

.PARAMETER ProfileCount
    Number of profiles to test (1-6, default: 6)

.PARAMETER Proxies
    Path to proxies file (default: proxies.txt next to this script)

.PARAMETER Headful
    Run with visible browser window

.PARAMETER NoCert
    Skip certificate generation

.PARAMETER SaveCert
    Save certificate text to this file path

.PARAMETER Binary
    Which binary phase(s) to run: local | fetched | both (default: both)

.EXAMPLE
    .\run_tests.ps1
    .\run_tests.ps1 -BrowserVersion official/prerelease/146.0.1-beta.50 -Headful
    .\run_tests.ps1 -Binary local
    .\run_tests.ps1 -Binary fetched -ProfileCount 3
#>

param(
    [string]$BrowserVersion = "official/stable",
    [int]   $ProfileCount   = 6,
    [string]$Proxies        = "",
    [switch]$Headful,
    [switch]$NoCert,
    [string]$SaveCert       = "",
    [string]$Binary         = "both"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# Ensure the console and Python subprocess both handle UTF-8 output correctly.
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::InputEncoding  = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING     = "utf-8"

# --- Resolve paths ---
$ScriptDir      = Split-Path -Parent $MyInvocation.MyCommand.Definition
$BuildTesterDir = [IO.Path]::Combine($ScriptDir, "..", "build-tester")
$PythonlibDir   = [IO.Path]::Combine($ScriptDir, "..", "pythonlib")
$VenvDir        = Join-Path $ScriptDir ".venv"
$PythonExe      = [IO.Path]::Combine($VenvDir, "Scripts", "python.exe")
$PipExe         = [IO.Path]::Combine($VenvDir, "Scripts", "pip.exe")
$ProxiesFile    = if ($Proxies) { $Proxies } else { Join-Path $ScriptDir "proxies.txt" }

# --- Validate -Binary ---
if ($Binary -notin @("local", "fetched", "both")) {
    Write-Error "ERROR: -Binary must be 'local', 'fetched', or 'both' (got: $Binary)"
    exit 1
}

Write-Host "==> Browser version: $BrowserVersion"
Write-Host "==> Profile count:   $ProfileCount"
Write-Host "==> Binary mode:     $Binary"

# --- npm deps (esbuild for TypeScript bundle) ---
$NodeModules = Join-Path $BuildTesterDir "node_modules"
if (-not (Test-Path $NodeModules)) {
    Write-Host "==> Installing build-tester npm dependencies..."
    Push-Location $BuildTesterDir
    npm install --silent
    Pop-Location
}

# --- Python venv ---
if (-not (Test-Path $VenvDir)) {
    Write-Host "==> Creating virtual environment..."
    python -m venv $VenvDir
}

# --- Build camoufox wheel ---
Write-Host "==> Building camoufox wheel from $PythonlibDir ..."
& $PipExe install -q build
$DistDir = [IO.Path]::Combine($PythonlibDir, "dist")
if (Test-Path $DistDir) {
    Remove-Item -Recurse -Force $DistDir
}
Push-Location $PythonlibDir
& $PythonExe -m build --wheel -o dist | Out-Null
Pop-Location

# --- Install wheel ---
Write-Host "==> Installing camoufox from local wheel..."
try { & $PipExe uninstall -y camoufox cloverlabs-camoufox 2>&1 | Out-Null } catch {}
$Wheel = Get-ChildItem ([IO.Path]::Combine($PythonlibDir, "dist", "*.whl")) | Select-Object -First 1
if (-not $Wheel) {
    Write-Error "ERROR: No wheel found in $PythonlibDir\dist"
    exit 1
}
& $PipExe install -q --force-reinstall $Wheel.FullName

# --- Locate locally compiled Windows binary ---
# Build output: ../camoufox-*/obj-*-windows-msvc/dist/bin/camoufox.exe
$LocalBin = $null
if ($Binary -ne "fetched") {
    $GlobPattern = [IO.Path]::Combine($ScriptDir, "..", "camoufox-*", "obj-*-windows-msvc", "dist", "bin", "camoufox.exe")
    $Candidates  = Get-ChildItem $GlobPattern -ErrorAction SilentlyContinue |
                   Sort-Object LastWriteTime -Descending
    if ($Candidates) {
        $LocalBin = $Candidates[0].FullName
    }
    if (-not $LocalBin) {
        if ($Binary -eq "local") {
            Write-Error "ERROR: -Binary local requested but no local build found at $GlobPattern"
            exit 1
        }
        Write-Host "==> No local build found -- skipping local-binary phase"
    }
}

# --- Build common args for run_tests.py ---
$CommonArgs = [System.Collections.Generic.List[string]]::new()
$CommonArgs.AddRange([string[]]@("--profile-count", $ProfileCount, "--proxies", $ProxiesFile))
if ($Headful) { $CommonArgs.Add("--headful") }
if ($NoCert)  { $CommonArgs.Add("--no-cert") }
if ($SaveCert) { $CommonArgs.AddRange([string[]]@("--save-cert", $SaveCert)) }

$LocalRc   = 0
$FetchedRc = 0

# --- Phase 1: locally compiled binary ---
if ($LocalBin) {
    Write-Host ""
    Write-Host ("=" * 60)
    Write-Host "  PHASE 1/2 -- Local binary: $LocalBin"
    Write-Host ("=" * 60)

    $Phase1Args = [System.Collections.Generic.List[string]]::new()
    $Phase1Args.Add([IO.Path]::Combine($ScriptDir, "run_tests.py"))
    $Phase1Args.AddRange([string[]]@("--executable-path", $LocalBin))
    $Phase1Args.AddRange($CommonArgs)

    & $PythonExe $Phase1Args
    $LocalRc = $LASTEXITCODE
}

# --- Phase 2: fetched binary ---
if ($Binary -ne "local") {
    Write-Host ""
    Write-Host ("=" * 60)
    Write-Host "  PHASE 2/2 -- Fetched binary: $BrowserVersion"
    Write-Host ("=" * 60)

    Write-Host "==> Setting browser version: $BrowserVersion"
    & $PythonExe -m camoufox set $BrowserVersion
    Write-Host "==> Fetching browser..."
    & $PythonExe -m camoufox fetch

    $Phase2Args = [System.Collections.Generic.List[string]]::new()
    $Phase2Args.Add([IO.Path]::Combine($ScriptDir, "run_tests.py"))
    $Phase2Args.AddRange([string[]]@("--browser-version", $BrowserVersion))
    $Phase2Args.AddRange($CommonArgs)

    & $PythonExe $Phase2Args
    $FetchedRc = $LASTEXITCODE
}

# --- Combined result ---
Write-Host ""
Write-Host ("=" * 60)
Write-Host "  COMBINED RESULT"
Write-Host ("=" * 60)
if ($LocalBin)           { Write-Host "  Local binary:   exit $LocalRc" }
if ($Binary -ne "local") { Write-Host "  Fetched binary: exit $FetchedRc" }

if (($LocalRc -ne 0) -or ($FetchedRc -ne 0)) {
    exit 1
}
exit 0
