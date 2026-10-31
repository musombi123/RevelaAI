$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Ollama = Get-Command ollama -ErrorAction SilentlyContinue
if (-not $Ollama) {
    Write-Host "Ollama is not installed on this computer. Install it from https://ollama.com/download before using local AI." -ForegroundColor Yellow
    exit 1
}
$env:OLLAMA_MODELS = Join-Path $Root "models"
$env:OLLAMA_HOST = "127.0.0.1:11434"
Write-Host "Local model storage: $env:OLLAMA_MODELS" -ForegroundColor Cyan
Write-Host "Stop any existing Ollama instance before starting this USB-local service." -ForegroundColor Yellow
Write-Host "This starts Ollama on loopback only. Press Ctrl+C to stop it." -ForegroundColor Yellow
& ollama serve
