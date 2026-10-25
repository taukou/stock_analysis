# 註冊 Windows 排程工作（目前使用者、登入時執行、不需系統管理員）。可重複執行。
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$py   = Join-Path $root '.venv\Scripts\python.exe'
$pyw  = Join-Path $root '.venv\Scripts\pythonw.exe'
foreach ($f in @($py, $pyw)) {
    if (-not (Test-Path $f)) { throw "找不到 $f，請先建立 .venv" }
}
$user = "$env:USERDOMAIN\$env:USERNAME"
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited

foreach ($name in @('StockChain-Sync', 'StockChain-Web')) {
    if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $name -Confirm:$false
    }
}

# StockChain-Sync：每天 16:00 + 登入後延遲 2 分鐘
$syncAction = New-ScheduledTaskAction -Execute $py -Argument 'run_sync.py' -WorkingDirectory $root
$daily = New-ScheduledTaskTrigger -Daily -At '16:00'
$logon = New-ScheduledTaskTrigger -AtLogOn -User $user
$logon.Delay = 'PT2M'
$syncSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2) -MultipleInstances IgnoreNew `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName 'StockChain-Sync' -Action $syncAction `
    -Trigger @($daily, $logon) -Settings $syncSettings -Principal $principal | Out-Null

# StockChain-Web：登入時啟動，不限執行時間
$webAction = New-ScheduledTaskAction -Execute $pyw -Argument 'serve.py' -WorkingDirectory $root
$webLogon = New-ScheduledTaskTrigger -AtLogOn -User $user
$webSettings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan) `
    -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName 'StockChain-Web' -Action $webAction `
    -Trigger $webLogon -Settings $webSettings -Principal $principal | Out-Null

Write-Host "已註冊（使用者 $user，專案 $root）："
Get-ScheduledTask -TaskName 'StockChain-*' | ForEach-Object {
    Write-Host ("  {0}  state={1}" -f $_.TaskName, $_.State)
}
Write-Host '  StockChain-Sync: 每天 16:00 + 登入後 2 分鐘 -> python.exe run_sync.py'
Write-Host '  StockChain-Web : 登入時 -> pythonw.exe serve.py (http://127.0.0.1:8765/)'
