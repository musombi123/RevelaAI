$ErrorActionPreference = "Stop"
$Version = "3.13.17"
$ArchiveName = "python-$Version-embed-amd64.zip"
$Url = "https://www.python.org/ftp/python/$Version/$ArchiveName"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$RuntimeRoot = Join-Path $Root "runtimes\python-win-x64"
$TempArchive = Join-Path $env:TEMP $ArchiveName

New-Item -ItemType Directory -Force -Path $RuntimeRoot | Out-Null
Write-Host "Downloading official Python $Version embeddable package..." -ForegroundColor Cyan
Invoke-WebRequest -Uri $Url -OutFile $TempArchive
$Hash = (Get-FileHash -Path $TempArchive -Algorithm SHA256).Hash.ToLowerInvariant()
Write-Host "Downloaded archive SHA-256: $Hash" -ForegroundColor Yellow
Write-Host "Compare this digest with the official Python release files before relying on the runtime." -ForegroundColor Yellow

Get-ChildItem -Path $RuntimeRoot -Force | Remove-Item -Recurse -Force
Expand-Archive -Path $TempArchive -DestinationPath $RuntimeRoot -Force
$Pth = Get-ChildItem -Path $RuntimeRoot -Filter "*._pth" | Select-Object -First 1
if (-not $Pth) { throw "Python embedded path configuration file was not found." }

$Lines = Get-Content -Path $Pth.FullName
$Lines = @($Lines | Where-Object { $_ -ne "..\..\src" -and $_ -ne "import site" })
$Lines += "..\..\src"
$Lines += "import site"
Set-Content -Path $Pth.FullName -Value $Lines -Encoding ASCII

$Python = Join-Path $RuntimeRoot "python.exe"
if (-not (Test-Path $Python)) { throw "python.exe was not extracted." }
& $Python --version
if ($LASTEXITCODE -ne 0) { throw "Embedded Python did not start correctly." }

Remove-Item -Path $TempArchive -Force
Write-Host "Portable Python runtime is ready at $RuntimeRoot" -ForegroundColor Green
Write-Host "Launch Start-RevelaAI.cmd from the USB root." -ForegroundColor Green
