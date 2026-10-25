# 重新啟動網站工作，並清掉殘留的 serve.py 程序（僅限本專案）。
$ErrorActionPreference = 'Continue'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Stop-ScheduledTask -TaskName 'StockChain-Web' -ErrorAction SilentlyContinue
Get-CimInstance Win32_Process -Filter "Name = 'pythonw.exe' OR Name = 'python.exe'" |
    Where-Object { $_.CommandLine -and $_.CommandLine -like '*serve.py*' -and $_.ExecutablePath -like "$root*" } |
    ForEach-Object {
        Write-Host "結束殘留程序 PID $($_.ProcessId)"
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
Start-Sleep -Seconds 1
Start-ScheduledTask -TaskName 'StockChain-Web'
Write-Host 'StockChain-Web 已重新啟動'
