param(
    [Parameter(Mandatory = $true)][string]$Version,
    [string]$OutputDirectory,
    [string]$PythonPath
)

$ErrorActionPreference = 'Stop'
$SmokeRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
if (-not $OutputDirectory) { $OutputDirectory = Join-Path $SmokeRoot "docs\release_outputs_$Version" }
New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
$SmokeOutputDirectory = (Resolve-Path -LiteralPath $OutputDirectory).Path
$SmokeName = if ($PythonPath) { 'source' } else { 'exe' }
$SmokeOutput = Join-Path $SmokeOutputDirectory "${SmokeName}_smoke.json"
$SmokeStart = @{
    FilePath = (Join-Path $SmokeRoot 'dist\LPA.exe')
    WorkingDirectory = $SmokeRoot
    WindowStyle = 'Hidden'
    PassThru = $true
}
if ($PythonPath) {
    $SmokeStart.FilePath = (Resolve-Path -LiteralPath $PythonPath).Path
    $SmokeStart.ArgumentList = @('-u', ('"{0}"' -f (Join-Path $SmokeRoot 'main.py')))
    $SmokeStart.RedirectStandardOutput = Join-Path $SmokeOutputDirectory 'source_stdout.txt'
    $SmokeStart.RedirectStandardError = Join-Path $SmokeOutputDirectory 'source_stderr.txt'
}
$SmokeProcess = Start-Process @SmokeStart
# Keep the process handle open so Windows PowerShell 5.1 retains ExitCode
# after a short-lived source process has closed its GUI.
$null = $SmokeProcess.Handle
$SmokeWindow = $null
$SmokeChildIds = @()
try {
    for ($SmokeAttempt = 0; $SmokeAttempt -lt 60; $SmokeAttempt++) {
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
    if ($SmokeTitle -ne "LPA $Version Beta") { throw "Unexpected window title: $SmokeTitle" }
    if (-not $SmokeResponding) { throw 'LPA window is not responding.' }
    if (-not $SmokeWindow.CloseMainWindow()) { throw 'Could not request normal window closure.' }
    if (-not $SmokeProcess.WaitForExit(15000)) { throw 'LPA did not exit after normal closure.' }
    if ($SmokeProcess.ExitCode -ne 0) { throw "LPA exited with code $($SmokeProcess.ExitCode)" }
    if ($PythonPath -and (Get-Item -LiteralPath $SmokeStart.RedirectStandardError).Length -ne 0) {
        throw 'Source GUI wrote to stderr; inspect source_stderr.txt.'
    }
    $SmokeRecord = [ordered]@{
        version = $Version
        launch_kind = $SmokeName
        executable = $SmokeStart.FilePath
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
