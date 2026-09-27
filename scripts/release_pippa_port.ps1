param(
    [int]$Port = 8501
)

try {
    $listeners = @(
        Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop |
            Sort-Object OwningProcess -Unique
    )
}
catch {
    # Some Windows sessions deny Get-NetTCPConnection even though netstat can
    # still identify the listener. Never mistake that denial for a free port.
    $listeners = @(
        & netstat -ano -p tcp |
            ForEach-Object {
                if ($_ -match "^\s*TCP\s+\S+:$Port\s+\S+\s+LISTENING\s+(\d+)\s*$") {
                    [pscustomobject]@{ OwningProcess = [int]$Matches[1] }
                }
            } |
            Sort-Object OwningProcess -Unique
    )
}

if ($listeners.Count -eq 0) {
    Write-Host "Port $Port is free."
    exit 0
}

foreach ($listener in $listeners) {
    $processId = $listener.OwningProcess
    try {
        $process = Get-CimInstance Win32_Process -Filter "ProcessId = $processId" -ErrorAction Stop
    }
    catch {
        Write-Host "Port $Port is held by PID $processId, but Windows would not identify it."
        Write-Host "For safety, PIPPA will not terminate an unidentified process."
        exit 2
    }

    $name = [string]$process.Name
    $commandLine = [string]$process.CommandLine
    $isPython = $name -match '^python(w)?\.exe$'
    $isStreamlitApp = (
        $commandLine -match '(?i)(-m\s+streamlit|streamlit(?:\.exe)?)' -and
        $commandLine -match '(?i)(^|[\\/\s])app\.py(?:\s|$)'
    )

    if (-not ($isPython -and $isStreamlitApp)) {
        Write-Host "Port $Port belongs to $name (PID $processId), not a verified PIPPA Streamlit process."
        Write-Host "For safety, PIPPA will not terminate it."
        exit 3
    }

    Write-Host "Stopping the previous PIPPA server on port $Port (PID $processId)..."
    Stop-Process -Id $processId -Force -ErrorAction Stop
}

$deadline = (Get-Date).AddSeconds(15)
while (
    (@(& netstat -ano -p tcp | Select-String "^\s*TCP\s+\S+:$Port\s+\S+\s+LISTENING\s+\d+\s*$").Count -gt 0) -and
    ((Get-Date) -lt $deadline)
) {
    Start-Sleep -Milliseconds 500
}

if (@(& netstat -ano -p tcp | Select-String "^\s*TCP\s+\S+:$Port\s+\S+\s+LISTENING\s+\d+\s*$").Count -gt 0) {
    Write-Host "The previous PIPPA server did not release port $Port."
    exit 4
}

Write-Host "Port $Port is now free."
exit 0
