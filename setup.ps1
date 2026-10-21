# AI-BRAIN - one-shot installer for Windows. Fully offline: every package is in wheels\. Requires Python 3.13.
#
#   powershell -ExecutionPolicy Bypass -File .\setup.ps1                 # interactive
#   powershell -ExecutionPolicy Bypass -File .\setup.ps1 -NonInteractive  # no questions (CI, scripted installs)
#   options: -Python C:\Python313\python.exe   -Firewall   -Autostart
param(
  [string]$Python = "",
  [switch]$NonInteractive,
  [switch]$Firewall,
  [switch]$Autostart
)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$Want = "3.13"
function Step($m) { Write-Host "`n== $m" -ForegroundColor Cyan }
function Ask($q) { if ($NonInteractive) { return "n" } ; return (Read-Host $q) }
function NewSecret { $b = New-Object byte[] 24; [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b); return (($b | ForEach-Object { $_.ToString("x2") }) -join "") }

Step "Python $Want"
$cands = @()
if ($Python) { $cands += ,@($Python) }
$cands += ,@("py", "-3.13"); $cands += ,@("python3.13"); $cands += ,@("python"); $cands += ,@("python3")
$py = $null; $pyArgs = @()
foreach ($c in $cands) {
  $exe = $c[0]; $a = @($c | Select-Object -Skip 1)
  try {
    $v = & $exe @a -c "import sys;print('%d.%d' % sys.version_info[:2])" 2>$null
    if ($LASTEXITCODE -eq 0 -and "$v".Trim() -eq $Want) { $py = $exe; $pyArgs = $a; break }
  } catch {}
}
if (-not $py) { throw "Python $Want not found. Install Python 3.13 (python.org installer, tick 'Add python.exe to PATH') or pass -Python <path to python.exe>." }
Write-Host "using $py $pyArgs (Python $Want)"
try { git --version | Out-Null } catch { Write-Host "WARNING: git is not on PATH; repositories cannot be cloned or updated." -ForegroundColor Yellow }

Step "Virtual environment (.venv)"
if (Test-Path .venv\Scripts\python.exe) {
  $have = & .\.venv\Scripts\python.exe -c "import sys;print('%d.%d' % sys.version_info[:2])" 2>$null
  if ("$have".Trim() -ne $Want) { Write-Host "existing .venv uses Python $($have) - recreating it"; Remove-Item -Recurse -Force .venv }
}
if (-not (Test-Path .venv\Scripts\python.exe)) { & $py @pyArgs -m venv .venv; if ($LASTEXITCODE -ne 0) { throw "venv creation failed" } }
$vpy = (Resolve-Path ".\.venv\Scripts\python.exe").Path

Step "Python packages (offline, from wheels\)"
& $vpy -m pip install --no-index --find-links wheels -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "offline package install failed: is the wheels\ folder complete? (see docs/14-OFFLINE-PACKAGING.md)" }
if (Test-Path wheels\ocr) {
  Step "OCR fallback (optional, from wheels\ocr\)"
  & $vpy -m pip install --no-index --no-deps --find-links wheels\ocr -r requirements-ocr.txt
  if ($LASTEXITCODE -ne 0) { Write-Host "OCR fallback not installed; pictures are described only by the vision model" }
}

Step "Code graph engine (codebase-memory-mcp)"
$zip = "bin\codebase-memory-mcp-windows-amd64.zip"
$exePath = "bin\windows\codebase-memory-mcp.exe"
if (-not (Test-Path $exePath)) {
  $want = ((Select-String -Path bin\SHA256SUMS -Pattern "windows-amd64.zip").Line -split "\s+")[0]
  $have = (Get-FileHash $zip -Algorithm SHA256).Hash.ToLower()
  if ($want -ne $have) { throw "Checksum mismatch for $zip (expected $want, got $have)" }
  Write-Host "checksum OK ($have)"
  Expand-Archive $zip -DestinationPath bin\windows -Force
  Unblock-File $exePath
}
& $exePath --version
if ($LASTEXITCODE -ne 0) { Write-Host "The engine did not run. If antivirus quarantined it (known false positive), ask IT to allow-list $exePath by SHA-256 (bin\SHA256SUMS)." -ForegroundColor Yellow }

Step "Configuration (.env, repos.json)"
if (-not (Test-Path .env)) {
  $text = Get-Content .env.example -Raw -Encoding UTF8
  $text = $text -replace "(?m)^BRAIN_API_TOKEN=$", ("BRAIN_API_TOKEN=" + (NewSecret))
  $text = $text -replace "(?m)^BRAIN_SECRET_KEY=$", ("BRAIN_SECRET_KEY=" + (NewSecret))
  [System.IO.File]::WriteAllText((Join-Path $PSScriptRoot ".env"), $text, (New-Object System.Text.UTF8Encoding $false))
  Write-Host "created .env (random BRAIN_API_TOKEN and BRAIN_SECRET_KEY generated)"
  if (-not $NonInteractive) {
    Write-Host "Fill in the REQUIRED values (BRAIN_UI_PASSWORD, BRAIN_LLM_BASE_URL, BRAIN_LLM_API_KEY, BRAIN_LLM_MODEL, BRAIN_EMBEDDING_MODEL, BRAIN_EMBEDDING_DIM), save and close Notepad."
    Start-Process notepad .env -Wait
  }
} else { Write-Host ".env exists: kept" }
if (-not (Test-Path repos.json)) {
  [System.IO.File]::WriteAllText((Join-Path $PSScriptRoot "repos.json"), "{`n  `"repos`": [],`n  `"sets`": {}`n}`n", (New-Object System.Text.UTF8Encoding $false))
  Write-Host "created an empty repos.json: add repositories in the UI (Repositories) or see repos.example.json"
}

Step "Self-check"
& $vpy brain.py doctor
if ($LASTEXITCODE -ne 0) { Write-Host "Some checks failed: fix .env (or the UI Settings page later) and run  .\brain.cmd doctor" -ForegroundColor Yellow }

$port = (Select-String -Path .env -Pattern '^BRAIN_PORT=(\d+)' | ForEach-Object { $_.Matches[0].Groups[1].Value }); if (-not $port) { $port = 8765 }
if ($Firewall -or (Ask "Open inbound TCP port $port in Windows Firewall so others can reach the UI? (needs admin) [y/N]") -eq "y") {
  Step "Firewall"
  Start-Process powershell -Verb RunAs -Wait -ArgumentList "-NoProfile -Command New-NetFirewallRule -DisplayName 'AI-BRAIN' -Direction Inbound -LocalPort $port -Protocol TCP -Action Allow -Profile Domain,Private"
}
if ($Autostart -or (Ask "Start the knowledge base automatically at logon (Task Scheduler)? [y/N]") -eq "y") {
  Step "Autostart"
  $act = New-ScheduledTaskAction -Execute $vpy -Argument "`"$PSScriptRoot\brain.py`" serve" -WorkingDirectory $PSScriptRoot
  Register-ScheduledTask -TaskName "AI-BRAIN" -Action $act -Trigger (New-ScheduledTaskTrigger -AtLogOn) -Force | Out-Null
  Write-Host "registered scheduled task 'AI-BRAIN'"
}

Write-Host "`nInstalled.`n  Start:     .\brain.cmd serve        then open http://<this-machine>:$port`n  Check:     .\brain.cmd doctor`n  Agents:    .\brain.cmd connect" -ForegroundColor Green
