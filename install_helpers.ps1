# Registers the fleet helpers as Windows scheduled tasks (all read-only). Run once:
#   right-click "Install fleet helpers.bat" > Run   (or: powershell -ExecutionPolicy Bypass -File install_helpers.ps1)
# Every task uses "run as soon as possible after a missed start", so a check the PC slept through
# runs when it wakes. Undo: powershell -File install_helpers.ps1 -Remove
# Start times are written without a time-zone offset, so they stay at the same clock time when
# daylight saving starts or ends (with an offset, Windows keeps the UTC moment and a 9:20am task
# runs at 8:20am all winter). -FixTimes rewrites every existing "Trading bot*" and "Fleet*" task's
# triggers the same way, without changing anything else about them.
param([switch]$Remove, [switch]$FixTimes)
function Use-LocalTime($trigger) {
  if ($trigger.StartBoundary) { $trigger.StartBoundary = ([datetime]$trigger.StartBoundary).ToString("yyyy-MM-ddTHH:mm:ss") }
  $trigger
}
if ($FixTimes) {
  foreach ($task in Get-ScheduledTask -TaskName "Trading bot*", "Fleet*" -ErrorAction SilentlyContinue) {
    $triggers = @($task.Triggers | ForEach-Object { Use-LocalTime $_ })
    Set-ScheduledTask -TaskName $task.TaskName -TaskPath $task.TaskPath -Trigger $triggers | Out-Null
    $next = (Get-ScheduledTaskInfo -TaskName $task.TaskName -TaskPath $task.TaskPath).NextRunTime
    Write-Host "$($task.TaskName): $(($triggers | ForEach-Object { $_.StartBoundary }) -join ', ')  next run $next"
  }
  exit
}
$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$py = Join-Path $dir ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $py)) { $py = Join-Path $dir ".venv\Scripts\python.exe" }
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 8)
$tasks = @(
  @{ Name = "Fleet maintenance (read-only)"; Args = "-m bot.maintenance --collect --alert";
     Trigger = New-ScheduledTaskTrigger -Daily -At "8:30PM" },
  @{ Name = "Fleet guard (read-only)"; Args = "-m bot.guard --loop 10 --until 16:10";
     Trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At "9:25AM" },
  @{ Name = "Fleet lab (weekly, read-only)"; Args = "-m bot.lab";
     Trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Saturday -At "10:00AM" },
  @{ Name = "Fleet reporter (weekly)"; Args = "-m bot.reporter";
     Trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At "6:00PM" },
  @{ Name = "Fleet alerts from GitHub"; Args = "-m bot.popup --cloud-alerts";
     Trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).Date -RepetitionInterval (New-TimeSpan -Minutes 15) },
  @{ Name = "Fleet summary at logon"; Args = "-m bot.popup --summary";
     Trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME }
)
foreach ($t in $tasks) {
  if ($Remove) {
    Unregister-ScheduledTask -TaskName $t.Name -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Removed $($t.Name)"
    continue
  }
  $action = New-ScheduledTaskAction -Execute $py -Argument $t.Args -WorkingDirectory $dir
  Register-ScheduledTask -TaskName $t.Name -Action $action -Trigger (Use-LocalTime $t.Trigger) -Settings $settings -Force | Out-Null
  Write-Host "Set up $($t.Name)"
}
Write-Host "Done. Tell Claude."
