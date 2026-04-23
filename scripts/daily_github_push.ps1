Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
$logDir = Join-Path $repoRoot 'logs'
$logPath = Join-Path $logDir 'daily_github_push.log'

if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Force -Path $logDir | Out-Null
}

function Write-Log {
    param([string]$Message)
    $timestamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    Add-Content -Path $logPath -Value "[$timestamp] $Message"
}

Set-Location $repoRoot
Write-Log 'Daily GitHub push job started.'

if (-not (Test-Path (Join-Path $repoRoot '.git'))) {
    throw 'Repository is not initialized.'
}

$snapshotStamp = Get-Date -Format 'yyyy-MM-dd'

git add -A
$status = git status --porcelain

if ([string]::IsNullOrWhiteSpace($status)) {
    Write-Log 'No file changes detected. Creating empty daily snapshot commit.'
    git commit --allow-empty -m "Daily snapshot $snapshotStamp" | Out-Null
} else {
    Write-Log 'Changes detected. Creating daily snapshot commit.'
    git commit -m "Daily snapshot $snapshotStamp" | Out-Null
}

Write-Log 'Pushing to origin/main.'
git push origin main | Out-Null
Write-Log 'Daily GitHub push job completed successfully.'
