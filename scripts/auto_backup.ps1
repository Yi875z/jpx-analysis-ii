# JPX Analysis - Auto Git Backup
$ProjectDir = "C:\CarSol\jpx-analysis"
$LogFile = "$ProjectDir\logs\backup.log"
$Date = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
$GitExe = "C:\Program Files\Git\cmd\git.exe"

if (-not (Test-Path "$ProjectDir\logs")) {
    New-Item -ItemType Directory -Path "$ProjectDir\logs" | Out-Null
}

$Status = & $GitExe -C $ProjectDir status --porcelain 2>&1
if (-not $Status) {
    Add-Content -Path $LogFile -Value "[$Date] No changes - skipped" -Encoding UTF8
    exit 0
}

& $GitExe -C $ProjectDir add .
$CommitMsg = "Auto backup: $(Get-Date -Format 'yyyy-MM-dd HH:mm')"
& $GitExe -C $ProjectDir commit -m $CommitMsg

$PushOutput = & $GitExe -C $ProjectDir push --set-upstream origin main 2>&1
if ($LASTEXITCODE -eq 0) {
    Add-Content -Path $LogFile -Value "[$Date] Backup OK: $CommitMsg" -Encoding UTF8
} else {
    Add-Content -Path $LogFile -Value "[$Date] Push FAILED: $PushOutput" -Encoding UTF8
}
