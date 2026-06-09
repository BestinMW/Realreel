Set-Location $PSScriptRoot\..\frontend

$lanIp = (
    Get-NetIPConfiguration -ErrorAction SilentlyContinue |
    Where-Object {
        $_.IPv4DefaultGateway -and
        $_.IPv4Address.IPAddress -match "^(10\.|192\.168\.|172\.(1[6-9]|2[0-9]|3[0-1])\.)" -and
        $_.InterfaceAlias -notmatch "Radmin|VPN|VirtualBox|Loopback"
    } |
    Select-Object -First 1 -ExpandProperty IPv4Address
).IPAddress

npm install

Write-Host "Starting frontend at http://0.0.0.0:3000"
if ($lanIp) {
    Write-Host "Other computers on the same network can open: http://$($lanIp):3000"
}

npm run dev -- --hostname 0.0.0.0 --port 3000
