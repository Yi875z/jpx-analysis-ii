$ProjectDir = "C:\CarSol\jpx-analysis"
$LogFile = "$ProjectDir\logs\debug.log"
$Date = Get-Date -Format "yyyy-MM-dd HH:mm:ss"

$env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")

$gitPath = (Get-Command git -ErrorAction SilentlyContinue).Source
Add-Content -Path $LogFile -Value "[$Date] git path: $gitPath" -Encoding UTF8

$Status = & git -C $ProjectDir status --porcelain 2>&1
Add-Content -Path $LogFile -Value "[$Date] Status type: $($Status.GetType().FullName)" -Encoding UTF8
Add-Content -Path $LogFile -Value "[$Date] Status count: $(if($null -ne $Status -and $Status -is [array]){$Status.Count}else{'not array'})" -Encoding UTF8
Add-Content -Path $LogFile -Value "[$Date] Status raw: '$Status'" -Encoding UTF8
Add-Content -Path $LogFile -Value "[$Date] not Status: $(-not $Status)" -Encoding UTF8
