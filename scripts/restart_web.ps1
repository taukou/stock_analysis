# 重新啟動網站工作，並清掉殘留的 serve.py 程序（僅限本專案），最後確認埠號有在監聽。
$ErrorActionPreference = 'Continue'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path

# 埠號：只從 .env 讀 APP_PORT 這個名稱，預設 8765
$port = 8765
$envFile = Join-Path $root '.env'
if (Test-Path $envFile) {
    $line = Get-Content $envFile | Where-Object { $_ -match '^\s*APP_PORT\s*=' } | Select-Object -First 1
    if ($line -and (($line -split '=', 2)[1].Trim().Trim('"').Trim("'")) -match '^\d+$') {
        $port = [int](($line -split '=', 2)[1].Trim().Trim('"').Trim("'"))
    }
}

function Get-PortOwners($p) {
    @(Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique)
}

Stop-ScheduledTask -TaskName 'StockChain-Web' -ErrorAction SilentlyContinue
$oldOwners = Get-PortOwners $port

# venv 的 pythonw.exe 只是啟動器，真正的伺服器是子程序（基底 Python），
# 所以用命令列（含本專案路徑與 serve.py）比對，而不是 ExecutablePath。
$rootEsc = [WildcardPattern]::Escape($root)
Get-CimInstance Win32_Process -Filter "Name = 'pythonw.exe' OR Name = 'python.exe'" |
    Where-Object { $_.CommandLine -and $_.CommandLine -like "*$rootEsc*serve.py*" } |
    ForEach-Object {
        Write-Host "結束殘留程序 PID $($_.ProcessId)"
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
Start-Sleep -Seconds 1
Start-ScheduledTask -TaskName 'StockChain-Web'

# 最多等 10 秒，確認埠號由新程序監聽
$ok = $false
for ($i = 0; $i -lt 10 -and -not $ok; $i++) {
    Start-Sleep -Seconds 1
    $owners = Get-PortOwners $port
    if ($owners.Count -gt 0 -and -not ($owners | Where-Object { $oldOwners -contains $_ })) { $ok = $true }
}
if ($ok) {
    Write-Host "OK：網站已重新啟動，埠 $port 由新程序監聽。"
    exit 0
}
Write-Host "FAIL：10 秒內埠 $port 沒有由新程序監聽，請查看 logs\web.log。"
exit 1
