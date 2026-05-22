<#
.SYNOPSIS
    Launch the Python tutor backend on Windows.

.DESCRIPTION
    Windows PowerShell counterpart to run.sh.

    Starts the FastAPI backend, which also serves the static PWA frontend
    on the same port. Prints the URL and, if requested, opens it in your
    default browser.

    If Ollama is unreachable we WARN but still start the server, so the user
    can browse lessons and exercises. Chat replies will fail with a clear
    503 from the backend until Ollama is up.

.PARAMETER Help
    Show this help and exit.

.PARAMETER TutorHost
    Bind address (default 127.0.0.1). Equivalent to env TUTOR_HOST.

.PARAMETER Port
    TCP port (default 8001). Equivalent to env TUTOR_PORT.

.PARAMETER Model
    Use Ollama model TAG (default gemma3:4b). Equivalent to env TUTOR_MODEL.

.PARAMETER OpenBrowser
    After the server reports healthy, open the URL in the default browser.

.PARAMETER NoLaunch
    Run all preflight checks and exit 0 without starting the server.

.PARAMETER SkipOllama
    Skip the Ollama reachability check. Equivalent to env TUTOR_SKIP_OLLAMA=1.

.PARAMETER Yes
    Auto-answer "yes" to the start-Ollama prompt.
    Equivalent to env PYTHON_TUTOR_ASSUME_YES=1.

.PARAMETER NonInteractive
    Never prompt. Equivalent to env TUTOR_NONINTERACTIVE=1.

.EXAMPLE
    .\run.ps1
    Start the server on 127.0.0.1:8001.

.EXAMPLE
    .\run.ps1 -OpenBrowser
    Start the server, then open http://localhost:8001/ once /api/health is green.

.EXAMPLE
    .\run.ps1 -Port 8042
    Use port 8042 instead of 8001.

.NOTES
    Exit codes:
      0  server started (or -NoLaunch dry-run succeeded)
      3  invalid CLI arguments
      4  port already in use (use -Port to choose another)
#>
#Requires -Version 5.1
[CmdletBinding()]
param(
    [switch]$Help,
    [string]$TutorHost,
    [int]$Port,
    [string]$Model,
    [switch]$OpenBrowser,
    [switch]$NoLaunch,
    [switch]$SkipOllama,
    [Alias('y')][switch]$Yes,
    [Alias('n')][switch]$NonInteractive
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if ($Help) {
    Get-Help -Detailed $PSCommandPath
    exit 0
}

# ----- repo root -------------------------------------------------------------
$repoRoot = Split-Path -Parent $PSCommandPath
Set-Location $repoRoot

# ----- pretty output ---------------------------------------------------------
$script:UseColor = $Host.UI.RawUI -and -not [Console]::IsOutputRedirected

function Write-Tag {
    param([string]$Color, [string]$Message, [switch]$Err)
    $line = "[run] $Message"
    if ($Err) {
        [Console]::Error.WriteLine($line)
    } elseif ($script:UseColor) {
        Write-Host $line -ForegroundColor $Color
    } else {
        Write-Host $line
    }
}
function Say  { param([string]$m) Write-Tag -Color 'Cyan'   -Message $m }
function Ok   { param([string]$m) Write-Tag -Color 'Green'  -Message $m }
function Warn { param([string]$m) Write-Tag -Color 'Yellow' -Message $m }
function ErrMsg { param([string]$m) Write-Tag -Color 'Red' -Message $m -Err }

# ----- defaults --------------------------------------------------------------
function Get-EnvDefault {
    param([string]$Name, [string]$Default)
    $v = [Environment]::GetEnvironmentVariable($Name)
    if ([string]::IsNullOrEmpty($v)) { return $Default } else { return $v }
}

if (-not $TutorHost) { $TutorHost = Get-EnvDefault 'TUTOR_HOST' '127.0.0.1' }
if (-not $Port)      { $Port      = [int](Get-EnvDefault 'TUTOR_PORT' '8001') }
if (-not $Model)     { $Model     = Get-EnvDefault 'TUTOR_MODEL' 'gemma3:4b' }

$TutorSkipOllama  = $SkipOllama.IsPresent     -or ((Get-EnvDefault 'TUTOR_SKIP_OLLAMA' '0') -eq '1')
$TutorNonInteract = $NonInteractive.IsPresent -or `
                    ((Get-EnvDefault 'TUTOR_NONINTERACTIVE' '0') -eq '1') -or `
                    ((Get-EnvDefault 'PYTHON_TUTOR_NONINTERACTIVE' '0') -eq '1')
$AssumeYes        = $Yes.IsPresent            -or ((Get-EnvDefault 'PYTHON_TUTOR_ASSUME_YES' '0') -eq '1')

# ----- prompt helper ---------------------------------------------------------
function Confirm-Prompt {
    param(
        [Parameter(Mandatory=$true)][string]$Question,
        [ValidateSet('default-no','default-yes')][string]$Default = 'default-no'
    )
    if ($AssumeYes) { Say "$Question [auto-yes]"; return $true }
    if ($TutorNonInteract) { Say "$Question [auto-no]"; return $false }
    $hasTty = $true
    try { if ([Console]::IsInputRedirected) { $hasTty = $false } } catch { $hasTty = $true }
    if (-not $hasTty) { Warn "$Question [no TTY -> no]"; return $false }
    $hint = if ($Default -eq 'default-yes') { '[Y/n]' } else { '[y/N]' }
    $reply = Read-Host "[run] $Question $hint"
    switch -Regex ($reply) {
        '^(y|Y|yes|Yes|YES)$' { return $true }
        '^(n|N|no|No|NO)$'    { return $false }
        '^$' { return ($Default -eq 'default-yes') }
        default { return $false }
    }
}

# ----- Ollama helpers --------------------------------------------------------
function Test-OllamaDaemon {
    try {
        $resp = Invoke-WebRequest -Uri 'http://localhost:11434/api/tags' `
            -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
        return ($resp.StatusCode -ge 200 -and $resp.StatusCode -lt 300)
    } catch { return $false }
}

function Start-OllamaNow {
    Say "starting 'ollama serve' in the background"
    $logPath = Join-Path ([IO.Path]::GetTempPath()) 'ollama-serve.log'
    try {
        $p = Start-Process -FilePath 'ollama' -ArgumentList 'serve' `
            -RedirectStandardOutput $logPath -RedirectStandardError $logPath `
            -WindowStyle Hidden -PassThru
    } catch {
        ErrMsg "failed to start 'ollama serve': $($_.Exception.Message)"
        return $false
    }
    for ($i = 0; $i -lt 20; $i++) {
        if (Test-OllamaDaemon) {
            Ok ("ollama serve is up (pid {0}; log: {1})" -f $p.Id, $logPath)
            return $true
        }
        Start-Sleep -Milliseconds 500
    }
    ErrMsg 'ollama serve did not become reachable on :11434 within 10s.'
    return $false
}

# ----- port-in-use detection -------------------------------------------------
function Test-PortInUse {
    param([string]$BindHost, [int]$P)
    $targets = @('127.0.0.1')
    if ($BindHost -ne '127.0.0.1' -and $BindHost -ne '0.0.0.0' -and $BindHost -ne 'localhost') {
        $targets += $BindHost
    }
    foreach ($t in $targets) {
        try {
            $client = New-Object System.Net.Sockets.TcpClient
            $iar = $client.BeginConnect($t, $P, $null, $null)
            $ok = $iar.AsyncWaitHandle.WaitOne(500)
            if ($ok -and $client.Connected) {
                $client.Close()
                return $true
            }
            $client.Close()
        } catch {
            # connect refused -> port free
        }
    }
    return $false
}

# ----- venv preflight --------------------------------------------------------
$venvDir    = Join-Path $repoRoot 'backend\.venv'
$venvUv     = Join-Path $venvDir 'Scripts\uvicorn.exe'
$venvPython = Join-Path $venvDir 'Scripts\python.exe'

if (-not (Test-Path $venvUv)) {
    Warn 'venv not found or uvicorn missing -- running .\install.ps1 first'
    $env:TUTOR_NONINTERACTIVE = '1'
    $env:TUTOR_SKIP_OLLAMA    = '1'
    $env:PYTHON_TUTOR_AUTOLAUNCH = '0'
    & (Join-Path $repoRoot 'install.ps1') -NoLaunch
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

# ----- Ollama probe ----------------------------------------------------------
if ($TutorSkipOllama) {
    Warn 'TUTOR_SKIP_OLLAMA=1 -- skipping Ollama reachability check'
} elseif (-not (Get-Command 'ollama' -ErrorAction SilentlyContinue)) {
    Warn 'ollama is not installed; chat replies will fail (UI still works).'
    Warn '  Run .\install.ps1 and answer "y" when asked to install Ollama, or:'
    Warn '  winget install -e --id Ollama.Ollama'
    Warn '  (or download from https://ollama.com/download/windows)'
} elseif (-not (Test-OllamaDaemon)) {
    Warn 'ollama is installed but the daemon is not reachable on :11434.'
    if (Confirm-Prompt "Start 'ollama serve' in the background now?") {
        if (-not (Start-OllamaNow)) {
            Warn "Could not auto-start. Chat replies will return 503 until you run 'ollama serve'."
        }
    } else {
        Warn "Continuing without Ollama. Chat replies will return 503 until you run 'ollama serve'."
    }
} else {
    Ok 'ollama daemon reachable on :11434'
}

# ----- port check ------------------------------------------------------------
if (Test-PortInUse -BindHost $TutorHost -P $Port) {
    ErrMsg "Port $Port is already in use on $TutorHost."
    ErrMsg 'Either stop whatever is listening, or pick another port:'
    ErrMsg "    .\run.ps1 -Port 8002"
    exit 4
}

if ($NoLaunch) {
    Ok "-NoLaunch: preflight passed; would start uvicorn on http://${TutorHost}:${Port}/"
    exit 0
}

# ----- launch ---------------------------------------------------------------
$env:TUTOR_MODEL          = $Model
$env:TUTOR_SERVE_FRONTEND = '1'
$url = "http://${TutorHost}:${Port}/"

Write-Host ''
Ok "starting backend on $url"
Ok 'open that URL in your browser. Press Ctrl-C to stop.'
Write-Host ''

if ($OpenBrowser) {
    # Background job that opens the browser once /api/health responds.
    Start-Job -ScriptBlock {
        param($u, $p)
        $healthy = "http://127.0.0.1:${p}/api/health"
        for ($i = 0; $i -lt 60; $i++) {
            try {
                $r = Invoke-WebRequest -Uri $healthy -UseBasicParsing -TimeoutSec 1 -ErrorAction Stop
                if ($r.StatusCode -ge 200 -and $r.StatusCode -lt 400) {
                    Start-Process $u | Out-Null
                    return
                }
            } catch { }
            Start-Sleep -Milliseconds 500
        }
    } -ArgumentList $url, $Port | Out-Null
}

Set-Location (Join-Path $repoRoot 'backend')
& $venvUv 'app.main:app' --host $TutorHost --port $Port
exit $LASTEXITCODE
