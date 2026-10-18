$ErrorActionPreference = 'Stop'
$SmokeRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$SmokeExe = Join-Path $SmokeRoot 'dist\LPA.exe'
$SmokeOutput = Join-Path $SmokeRoot 'docs\thermal_beta_outputs_0160\exe_smoke.json'
$SmokeProcess = Start-Process -FilePath $SmokeExe -WorkingDirectory $SmokeRoot -WindowStyle Hidden -PassThru
$SmokeWindow = $null
$SmokeChildIds = @()
try {
    for ($SmokeAttempt = 0; $SmokeAttempt -lt 30; $SmokeAttempt++) {
        $SmokeChildIds = @(Get-CimInstance Win32_Process -Filter "ParentProcessId = $($SmokeProcess.Id)" | Select-Object -ExpandProperty ProcessId)
        $SmokeIds = @($SmokeProcess.Id) + $SmokeChildIds
        $SmokeWindows = @(Get-Process -Id $SmokeIds -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -ne 0 })
        if ($SmokeWindows.Count -gt 0) {
            $SmokeWindow = $SmokeWindows[0]
            break
        }
        if ($SmokeProcess.HasExited) { throw "LPA exited before creating a window: $($SmokeProcess.ExitCode)" }
        Start-Sleep -Milliseconds 500
    }
    if ($null -eq $SmokeWindow) { throw 'LPA did not create a window within the smoke timeout.' }
    $SmokeTitle = $SmokeWindow.MainWindowTitle
    $SmokeResponding = $SmokeWindow.Responding
    if ($SmokeTitle -ne 'LPA 0.16.0b1 Beta') { throw "Unexpected window title: $SmokeTitle" }
    if (-not $SmokeResponding) { throw 'LPA window is not responding.' }
    if (-not $SmokeWindow.CloseMainWindow()) { throw 'Could not request normal window closure.' }
    if (-not $SmokeProcess.WaitForExit(15000)) { throw 'LPA did not exit after normal closure.' }
    if ($SmokeProcess.ExitCode -ne 0) { throw "LPA exited with code $($SmokeProcess.ExitCode)" }
    $SmokeRecord = [ordered]@{
        version = '0.16.0b1'
        title = $SmokeTitle
        responding = $SmokeResponding
        parent_process_id = $SmokeProcess.Id
        window_process_id = $SmokeWindow.Id
        normal_close = $true
        exit_code = $SmokeProcess.ExitCode
    }
    $SmokeRecord | ConvertTo-Json | Set-Content -LiteralPath $SmokeOutput -Encoding utf8
    $SmokeRecord | ConvertTo-Json
} finally {
    foreach ($SmokeOwnId in (@($SmokeProcess.Id) + $SmokeChildIds)) {
        $SmokeOwnProcess = Get-Process -Id $SmokeOwnId -ErrorAction SilentlyContinue
        if ($null -ne $SmokeOwnProcess) { Stop-Process -Id $SmokeOwnId -ErrorAction SilentlyContinue }
    }
}
