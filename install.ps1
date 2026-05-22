<#
.SYNOPSIS
    Idempotent Windows installer for the offline Python tutor.

.DESCRIPTION
    Windows PowerShell counterpart to install.sh.

    What this script does:
      1. Prints a one-screen preflight report (OS, Python, Ollama, model).
      2. Verifies Python >= 3.10.
      3. Creates backend/.venv if missing; rebuilds it if broken or if the
         repo has been moved since it was created (virtualenvs are path-
         sensitive -- moving them silently breaks the shebangs inside).
      4. Installs backend dependencies (dev extras included for tests).
         On network/DNS failure, prints actionable offline-wheelhouse hints.
      5. Detects Ollama, the daemon, and the default model. For each
         missing prerequisite it prompts y/N. Default answer is "no";
         nothing is installed silently. Auto-install path uses winget when
         confirmed; manual download link is offered otherwise.
      6. Optionally launches .\run.ps1 -- gated by y/N.

.PARAMETER Help
    Show this help and exit. Equivalent to -? or Get-Help.

.PARAMETER Yes
    Assume "yes" to every prompt (installs Ollama via winget, starts the
    daemon, pulls the model, launches). Equivalent to env
    PYTHON_TUTOR_ASSUME_YES=1.

.PARAMETER NonInteractive
    Never prompt; auto-answer "no" to every prompt.
    Equivalent to env TUTOR_NONINTERACTIVE=1.

.PARAMETER NoLaunch
    Do not prompt to launch .\run.ps1 after install.

.PARAMETER SkipOllama
    Skip every Ollama probe. Equivalent to env TUTOR_SKIP_OLLAMA=1.

.PARAMETER SkipModelPull
    Skip 'ollama pull'. Equivalent to env TUTOR_SKIP_MODEL_PULL=1.

.PARAMETER Model
    Pull and check for this tag instead of gemma3:4b.
    Equivalent to env TUTOR_MODEL=TAG.

.EXAMPLE
    .\install.ps1
    Run the interactive installer.

.EXAMPLE
    .\install.ps1 -Yes
    Trusted host: install Ollama (via winget), pull model, launch.

.EXAMPLE
    .\install.ps1 -NonInteractive
    CI mode: never prompt, default every host-level step to "no".

.NOTES
    Exit codes:
      0  success
      1  Python is too old or missing
      2  pip install failed
      3  invalid CLI arguments
#>
#Requires -Version 5.1
[CmdletBinding()]
param(
    [switch]$Help,
    [Alias('y')][switch]$Yes,
    [Alias('n')][switch]$NonInteractive,
    [switch]$NoLaunch,
    [switch]$SkipOllama,
    [switch]$SkipModelPull,
    [string]$Model
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
    param([string]$Tag, [string]$Color, [string]$Message, [switch]$Err)
    $line = "[install] $Message"
    if ($Err) {
        if ($script:UseColor) { Write-Host $line -ForegroundColor $Color -ErrorAction SilentlyContinue }
        [Console]::Error.WriteLine($line)
    } else {
        if ($script:UseColor) {
            Write-Host $line -ForegroundColor $Color
        } else {
            Write-Host $line
        }
    }
}
function Say  { param([string]$m) Write-Tag -Color 'Cyan'   -Message $m }
function Ok   { param([string]$m) Write-Tag -Color 'Green'  -Message $m }
function Warn { param([string]$m) Write-Tag -Color 'Yellow' -Message $m }
function ErrMsg { param([string]$m) Write-Tag -Color 'Red' -Message $m -Err }

# ----- defaults / env overrides ---------------------------------------------
function Get-EnvDefault {
    param([string]$Name, [string]$Default)
    $v = [Environment]::GetEnvironmentVariable($Name)
    if ([string]::IsNullOrEmpty($v)) { return $Default } else { return $v }
}

$TutorModel        = if ($Model) { $Model } else { Get-EnvDefault 'TUTOR_MODEL' 'gemma3:4b' }
$TutorSkipOllama   = $SkipOllama.IsPresent     -or ((Get-EnvDefault 'TUTOR_SKIP_OLLAMA' '0') -eq '1')
$TutorSkipPull     = $SkipModelPull.IsPresent  -or ((Get-EnvDefault 'TUTOR_SKIP_MODEL_PULL' '0') -eq '1')
$TutorNonInteract  = $NonInteractive.IsPresent -or `
                     ((Get-EnvDefault 'TUTOR_NONINTERACTIVE' '0') -eq '1') -or `
                     ((Get-EnvDefault 'PYTHON_TUTOR_NONINTERACTIVE' '0') -eq '1')
$AssumeYes         = $Yes.IsPresent            -or ((Get-EnvDefault 'PYTHON_TUTOR_ASSUME_YES' '0') -eq '1')
$AutoLaunch        = (Get-EnvDefault 'PYTHON_TUTOR_AUTOLAUNCH' '0') -eq '1'

# ----- prompt helper ---------------------------------------------------------
function Confirm-Prompt {
    param(
        [Parameter(Mandatory=$true)][string]$Question,
        [ValidateSet('default-no','default-yes')][string]$Default = 'default-no'
    )
    if ($AssumeYes) {
        Say "$Question [auto-yes]"
        return $true
    }
    if ($TutorNonInteract) {
        Say "$Question [auto-no]"
        return $false
    }
    # Detect headless / no-TTY (no real console input) -> answer "no".
    $hasTty = $true
    try {
        if ([Console]::IsInputRedirected) { $hasTty = $false }
    } catch { $hasTty = $true }
    if (-not $hasTty) {
        Warn "$Question [no TTY -> no]"
        return $false
    }
    $hint = if ($Default -eq 'default-yes') { '[Y/n]' } else { '[y/N]' }
    $reply = Read-Host "[install] $Question $hint"
    switch -Regex ($reply) {
        '^(y|Y|yes|Yes|YES)$' { return $true }
        '^(n|N|no|No|NO)$'    { return $false }
        '^$' { return ($Default -eq 'default-yes') }
        default { return $false }
    }
}

# ----- OS / arch detection ---------------------------------------------------
$osKind = if ($IsWindows -or $env:OS -eq 'Windows_NT') { 'windows' }
          elseif ($IsLinux) { 'linux' }
          elseif ($IsMacOS) { 'macos' }
          else { 'other' }

# ----- Python detection ------------------------------------------------------
# Try the Python launcher first (the default Windows install), then bare names.
# We accept any 3.10+.
function Get-PyVersionInfo {
    param([string]$Exe, [string[]]$ExtraArgs = @())
    try {
        $argsList = @()
        if ($ExtraArgs) { $argsList += $ExtraArgs }
        $argsList += @('-c', 'import sys; print("%d %d" % sys.version_info[:2])')
        $out = & $Exe @argsList 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $out) { return $null }
        $parts = ($out.Trim() -split '\s+')
        if ($parts.Count -lt 2) { return $null }
        return [pscustomobject]@{
            Exe       = $Exe
            ExtraArgs = $ExtraArgs
            Major     = [int]$parts[0]
            Minor     = [int]$parts[1]
        }
    } catch {
        return $null
    }
}

$pyCandidates = @()
# Windows launcher with explicit version flags (newest first).
foreach ($v in @('3.13','3.12','3.11','3.10')) {
    if (Get-Command 'py' -ErrorAction SilentlyContinue) {
        $info = Get-PyVersionInfo -Exe 'py' -ExtraArgs @("-$v")
        if ($info) { $pyCandidates += $info }
    }
}
# Bare 'python' / 'python3'.
foreach ($name in @('python','python3','python3.13','python3.12','python3.11','python3.10')) {
    if (Get-Command $name -ErrorAction SilentlyContinue) {
        $info = Get-PyVersionInfo -Exe $name
        if ($info) { $pyCandidates += $info }
    }
}

# Pick newest >= 3.10.
$PY        = $null
$pyVerText = $null
foreach ($cand in ($pyCandidates | Sort-Object @{Expression='Major';Descending=$true},@{Expression='Minor';Descending=$true})) {
    if ($cand.Major -gt 3 -or ($cand.Major -eq 3 -and $cand.Minor -ge 10)) {
        $PY        = $cand
        $pyVerText = "$($cand.Major).$($cand.Minor)"
        break
    }
}

function Invoke-Py {
    param([Parameter(ValueFromRemainingArguments=$true)][string[]]$Args)
    & $PY.Exe @($PY.ExtraArgs + $Args)
}

# ----- Ollama detection ------------------------------------------------------
function Get-OllamaPath {
    $cmd = Get-Command 'ollama' -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    return $null
}

function Test-OllamaDaemon {
    try {
        $resp = Invoke-WebRequest -Uri 'http://localhost:11434/api/tags' `
            -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
        return ($resp.StatusCode -ge 200 -and $resp.StatusCode -lt 300)
    } catch {
        return $false
    }
}

function Test-OllamaModelPresent {
    param([string]$Tag)
    try {
        $resp = Invoke-WebRequest -Uri 'http://localhost:11434/api/tags' `
            -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
        return $resp.Content -match [regex]::Escape("`"$Tag`"")
    } catch {
        return $false
    }
}

$ollamaPath = Get-OllamaPath
if ($ollamaPath) {
    $ollamaStatus = if (Test-OllamaDaemon) { 'installed + daemon reachable' } else { 'installed (daemon down)' }
} else {
    $ollamaStatus = 'not installed'
}

# ----- preflight report ------------------------------------------------------
Write-Host ''
Say 'Preflight'
Say "  repo:    $repoRoot"
Say "  os:      Windows ($osKind, PSv$($PSVersionTable.PSVersion))"
if ($PY) {
    $verLabel = "$($PY.Exe) $($PY.ExtraArgs -join ' ')".Trim()
    Say "  python:  $verLabel ($pyVerText)"
} else {
    Say '  python:  (none >=3.10 found)'
}
$ollamaPathLabel = if ($ollamaPath) { $ollamaPath } else { '(not found)' }
Say "  ollama:  $ollamaStatus [$ollamaPathLabel]"
Say "  model:   $TutorModel"
if ($TutorSkipOllama)        { Say '  mode:    skip-ollama' }
elseif ($AssumeYes)          { Say '  mode:    assume-yes' }
elseif ($TutorNonInteract)   { Say '  mode:    noninteractive (auto-no)' }
else                         { Say '  mode:    interactive' }
Write-Host ''

# ----- 1. Python -------------------------------------------------------------
if (-not $PY) {
    ErrMsg 'Python 3.10+ is required and was not found on PATH.'
    ErrMsg '  Recommended: install via the Microsoft Store ("Python 3.12") or from'
    ErrMsg '  https://www.python.org/downloads/windows/ (check "Add python.exe to PATH").'
    ErrMsg '  Or via winget:  winget install -e --id Python.Python.3.12'
    exit 1
}
Ok "using $($PY.Exe) $($PY.ExtraArgs -join ' ') ($pyVerText)"

# ----- 2. venv ---------------------------------------------------------------
$venvDir    = Join-Path $repoRoot 'backend\.venv'
$venvMarker = Join-Path $venvDir '.tutor_repo_root'
$venvPython = Join-Path $venvDir 'Scripts\python.exe'
$venvPip    = Join-Path $venvDir 'Scripts\pip.exe'

$needsCreate  = $false
$needsRebuild = $false

if (-not (Test-Path $venvDir)) {
    $needsCreate = $true
} elseif (-not (Test-Path $venvPython)) {
    Warn "venv at $venvDir looks broken; rebuilding"
    $needsRebuild = $true
} else {
    & $venvPython -c 'import sys' *> $null
    if ($LASTEXITCODE -ne 0) {
        Warn "venv at $venvDir looks broken; rebuilding"
        $needsRebuild = $true
    } elseif (Test-Path $venvMarker) {
        $saved = (Get-Content -LiteralPath $venvMarker -ErrorAction SilentlyContinue | Select-Object -First 1)
        if ($saved -and $saved.Trim() -ne $repoRoot) {
            Warn 'venv was created in a different directory:'
            Warn "  saved: $saved"
            Warn "  now:   $repoRoot"
            Warn 'virtualenvs are path-sensitive; rebuilding.'
            $needsRebuild = $true
        }
    }
}

if ($needsRebuild) {
    Remove-Item -LiteralPath $venvDir -Recurse -Force
    $needsCreate = $true
}

if ($needsCreate) {
    Say "creating virtualenv at $venvDir"
    Invoke-Py -m venv $venvDir
    if ($LASTEXITCODE -ne 0) {
        ErrMsg "failed to create venv at $venvDir"
        exit 2
    }
} else {
    Ok "venv already present at $venvDir"
}
Set-Content -LiteralPath $venvMarker -Value $repoRoot -Encoding ASCII

# ----- 3. dependencies -------------------------------------------------------
Say 'upgrading pip and installing backend deps'
$pipLog = Join-Path ([IO.Path]::GetTempPath()) ("tutor-pip-{0}.log" -f ([Guid]::NewGuid().ToString('N').Substring(0,8)))

function Invoke-Pip {
    # Returns $true on success; writes verbose output to $pipLog.
    & $venvPython -m pip install --upgrade pip *>> $pipLog
    if ($LASTEXITCODE -ne 0) { return $false }
    & $venvPip install -r (Join-Path $repoRoot 'backend\requirements-dev.txt') *>> $pipLog
    if ($LASTEXITCODE -ne 0) { return $false }
    return $true
}

$pipOk = $false
try {
    $pipOk = Invoke-Pip
} catch {
    $pipOk = $false
}

if ($pipOk) {
    Remove-Item -LiteralPath $pipLog -Force -ErrorAction SilentlyContinue
    Ok 'backend dependencies installed'
} else {
    ErrMsg 'pip install failed. Last 25 lines of pip output:'
    if (Test-Path $pipLog) {
        Get-Content -LiteralPath $pipLog -Tail 25 | ForEach-Object { [Console]::Error.WriteLine($_) }
    }
    ErrMsg "Full log: $pipLog"
    Write-Host ''
    $netHint = $false
    if (Test-Path $pipLog) {
        $logTxt = Get-Content -LiteralPath $pipLog -Raw -ErrorAction SilentlyContinue
        if ($logTxt -and ($logTxt -match '(?i)name or service not known|temporary failure in name resolution|could not resolve|timed out|getaddrinfo|cannot connect to proxy|ssl: certificate')) {
            $netHint = $true
        }
    }
    if ($netHint) {
        ErrMsg 'This looks like a network/DNS/proxy problem reaching pypi.org.'
        ErrMsg 'Workarounds:'
        ErrMsg '  1. Retry from a network with pypi.org reachable.'
        ErrMsg '  2. Behind a corporate proxy (PowerShell):'
        ErrMsg '       $env:HTTPS_PROXY = "http://proxy.example:8080"'
        ErrMsg '       $env:HTTP_PROXY  = "http://proxy.example:8080"'
        ErrMsg '  3. Fully offline -- build a wheelhouse on a connected host:'
        ErrMsg '       pip download -d wheelhouse -r backend/requirements-dev.txt'
        ErrMsg '     copy wheelhouse\ to this host, then re-run as:'
        ErrMsg '       $env:PIP_NO_INDEX = "1"'
        ErrMsg "       `$env:PIP_FIND_LINKS = `"$repoRoot\wheelhouse`""
        ErrMsg '       .\install.ps1'
        ErrMsg '  4. Internal mirror:'
        ErrMsg '       $env:PIP_INDEX_URL = "https://pypi.internal/simple"'
        ErrMsg '       .\install.ps1'
        ErrMsg "See docs/install-runtime-workflow.md -> 'Offline / restricted networks'."
    }
    exit 2
}

# ----- 4. Ollama -------------------------------------------------------------
function Show-OllamaManualHint {
    Warn 'You can install Ollama manually any time:'
    Warn '  winget install -e --id Ollama.Ollama'
    Warn '  (or download from https://ollama.com/download/windows)'
    Warn 'Then re-run .\install.ps1 to pull the default model.'
    Warn 'The web UI will still work -- chat replies will fail until Ollama is up.'
}

function Install-OllamaNow {
    if (-not (Get-Command 'winget' -ErrorAction SilentlyContinue)) {
        ErrMsg 'winget is required to install Ollama on Windows automatically.'
        ErrMsg '  Update App Installer from the Microsoft Store and retry, or'
        ErrMsg '  download Ollama from https://ollama.com/download/windows and re-run.'
        return $false
    }
    Say 'running: winget install -e --id Ollama.Ollama --accept-source-agreements --accept-package-agreements'
    & winget install -e --id Ollama.Ollama --accept-source-agreements --accept-package-agreements
    if ($LASTEXITCODE -ne 0) {
        ErrMsg 'winget install Ollama failed.'
        return $false
    }
    # PATH may not be refreshed in this session -- pick up the new exe via the
    # default install location, falling back to a fresh PATH lookup.
    $maybe = @(
        (Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe'),
        (Join-Path $env:ProgramFiles 'Ollama\ollama.exe')
    ) | Where-Object { Test-Path $_ } | Select-Object -First 1
    if ($maybe) {
        # Prepend the install dir to the current session PATH so subsequent
        # Get-Command 'ollama' calls in this script find it.
        $env:PATH = "$(Split-Path -Parent $maybe);$env:PATH"
    }
    Ok 'Ollama installed via winget.'
    return $true
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
    ErrMsg "Inspect $logPath or run 'ollama serve' in another terminal."
    return $false
}

if ($TutorSkipOllama) {
    Warn 'TUTOR_SKIP_OLLAMA=1 -- skipping Ollama checks'
} else {
    # 4a. Binary present?
    if (-not (Get-OllamaPath)) {
        Warn 'Ollama is not installed.'
        if (Confirm-Prompt 'Install Ollama now? (will run: winget install Ollama.Ollama)') {
            if (Install-OllamaNow) {
                $newPath = Get-OllamaPath
                if ($newPath) { Ok "ollama is installed ($newPath)" } else { Warn 'ollama installed but not yet on PATH for this session; open a new terminal.' }
            } else {
                Show-OllamaManualHint
            }
        } else {
            Show-OllamaManualHint
        }
    }

    # 4b. Daemon reachable?
    $ollamaPath = Get-OllamaPath
    if ($ollamaPath) {
        Ok "ollama is installed ($ollamaPath)"
        if (Test-OllamaDaemon) {
            Ok 'ollama daemon is reachable on http://localhost:11434'
        } else {
            Warn 'Ollama is installed but the daemon is not running on :11434.'
            if (Confirm-Prompt "Start 'ollama serve' in the background now?") {
                if (-not (Start-OllamaNow)) {
                    Warn "Could not auto-start. Run 'ollama serve' in another PowerShell and re-run .\install.ps1."
                }
            } else {
                Warn "Skipping auto-start. Run 'ollama serve' yourself in another terminal."
            }
        }
    }

    # 4c. Default model present?
    $ollamaPath = Get-OllamaPath
    if ($ollamaPath -and (Test-OllamaDaemon)) {
        if ($TutorSkipPull) {
            Warn 'TUTOR_SKIP_MODEL_PULL=1 -- skipping model pull'
        } elseif (Test-OllamaModelPresent -Tag $TutorModel) {
            Ok "model '$TutorModel' already present"
        } else {
            Warn "Model '$TutorModel' is not present locally."
            if (Confirm-Prompt "Pull '$TutorModel' now? (this can take several minutes)") {
                & ollama pull $TutorModel
                if ($LASTEXITCODE -eq 0) {
                    Ok "model '$TutorModel' ready"
                } else {
                    Warn "ollama pull failed. You can retry later with: ollama pull $TutorModel"
                }
            } else {
                Warn "Skipping pull. Retry later with: ollama pull $TutorModel"
            }
        }
    }
}

# ----- 5. Optional auto-launch ----------------------------------------------
Write-Host ''
Ok 'install complete.'
Write-Host ''

$launchNow = $false
if ($NoLaunch) {
    # --no-launch wins over everything else.
} elseif ($AutoLaunch) {
    $launchNow = $true
} elseif (Confirm-Prompt 'Launch the tutor now (.\run.ps1)?') {
    $launchNow = $true
}

if ($launchNow) {
    Ok 'launching .\run.ps1'
    $env:TUTOR_MODEL = $TutorModel
    & (Join-Path $repoRoot 'run.ps1')
    exit $LASTEXITCODE
}

Write-Host 'Next step:'
Write-Host '    .\run.ps1        # starts the tutor at http://localhost:8001/'
Write-Host ''
Write-Host 'Then open http://localhost:8001/ in your browser.'
