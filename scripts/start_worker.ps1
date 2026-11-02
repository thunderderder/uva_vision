param(
    [string]$BaseUrl = "http://127.0.0.1:8030/"
)
$ErrorActionPreference = "Stop"
try {
    $st = Invoke-RestMethod -Uri ($BaseUrl.TrimEnd("/") + "/api/pra/worker/status") -TimeoutSec 15
    if ($st.running) {
        Write-Host "[Worker] already running pid $($st.pid) phase $($st.phase)"
        exit 0
    }
    $r = Invoke-RestMethod -Uri ($BaseUrl.TrimEnd("/") + "/api/pra/worker/start") -Method POST `
        -ContentType "application/json" -Body '{"until_empty":false}' -TimeoutSec 60
    Write-Host "[Worker] started pid $($r.pid) phase $($r.phase)"
    if ($r.phase -ne "ready") {
        Write-Host "Qwen loading ~10-30s; check Worker status on config page"
    }
} catch {
    Write-Host "[Worker] failed: $($_.Exception.Message)"
    exit 1
}
