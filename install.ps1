# One-time install on Windows with native Claude Code and the Tailscale app logged in:
#   powershell -ExecutionPolicy Bypass -File install.ps1 gc-hub.<tailnet>.ts.net
# (WSL users run install.sh inside WSL instead.)
param([Parameter(Mandatory)][string]$Hub)
$ErrorActionPreference = "Stop"
foreach ($c in "python", "claude") { if (-not (Get-Command $c -ErrorAction SilentlyContinue)) { throw "$c is required on PATH" } }
$dir = $PSScriptRoot
$gc = "$HOME\.gc"
New-Item -ItemType Directory -Force "$gc\bin", "$gc\inbox", "$HOME\.claude\skills" | Out-Null
Set-Content "$gc\bin\gc.cmd" "@python `"$dir\bridge\gc`" %*" -Encoding ascii
$unix = $dir -replace '\\', '/'
Set-Content "$gc\bin\gc" "#!/bin/sh`nexec python `"$unix/bridge/gc`" `"`$@`"`n" -Encoding ascii -NoNewline   # for Git Bash (claude's hooks and Bash tool)
$link = "$HOME\.claude\skills\gc"
if (Test-Path $link) { (Get-Item $link).Delete() }
New-Item -ItemType Junction -Path $link -Target "$dir\plugin" | Out-Null
Set-Content "$gc\config.json" "{`"hub`": `"$Hub`"}" -Encoding ascii
Copy-Item "$dir\INSTALL_VERSION" "$gc\install_version"
& "$gc\bin\gc.cmd" ensure-bridge
Start-Sleep 4
& "$gc\bin\gc.cmd" status
Write-Host ""
Write-Host "done. Start claude as usual: /peers shows sessions shared with you;"
Write-Host "say 'share this session with <name>' to share yours. Web page: http://${Hub}:7778/"
