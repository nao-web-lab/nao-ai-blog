# 楽天商品LP 自動生成 - タスクスケジューラ登録
# 使い方: このファイルを右クリック →「PowerShellで実行」
#
# 登録されるタスク:
#   NaoAiBlog-RakutenLP   毎日10:00に起動し、品質基準を満たす商品をできるだけ多くLP化 → GitHubへ公開 → LINEに結果通知
#
# 楽天APIは許可IP(このPC)からしか使えないため、GitHub Actionsではなくこの方式で実行します。
# 6:30/18:30 のThreads自動投稿(RakutenThreadsAuto)とはGeminiの利用が重ならない時刻にしています。

$ErrorActionPreference = "Stop"

$pythonExe = "C:\Users\user\AppData\Local\Programs\Python\Python312\pythonw.exe"
$toolDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoDir = (Resolve-Path (Join-Path $toolDir "..\..")).Path

if (-not (Test-Path $pythonExe)) {
    Write-Error "Pythonが見つかりません: $pythonExe"
    exit 1
}

$settings = New-ScheduledTaskSettingsSet `
    -WakeToRun `
    -StartWhenAvailable `
    -DontStopOnIdleEnd `
    -ExecutionTimeLimit (New-TimeSpan -Hours 6) `
    -RestartCount 1 `
    -RestartInterval (New-TimeSpan -Minutes 15)
$settings.DisallowStartIfOnBatteries = $false
$settings.StopIfGoingOnBatteries = $false

$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive
$action = New-ScheduledTaskAction -Execute $pythonExe -Argument "tools\rakuten-lp\run_daily.py --notify" -WorkingDirectory $repoDir
$trigger = New-ScheduledTaskTrigger -Daily -At "10:00"

Register-ScheduledTask -TaskName "NaoAiBlog-RakutenLP" -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal -Force | Out-Null

Write-Output "登録しました: NaoAiBlog-RakutenLP (毎日 10:00)"
Write-Output "タスクスケジューラのアプリで「NaoAiBlog-RakutenLP」で検索すると確認できます。"
