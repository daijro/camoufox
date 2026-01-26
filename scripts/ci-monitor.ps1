# ci-monitor.ps1 - Poll GitHub Actions runs and re-trigger by pushing an empty commit on failure
# Usage: powershell -ExecutionPolicy Bypass -File scripts\ci-monitor.ps1

$owner = 'malithwishwa02-dot'
$repo = 'Lucid'
$maxAttempts = 60
$intervalSec = 60

Write-Host "Starting CI monitor for ${owner}/${repo} - maxAttempts=${maxAttempts} interval=${intervalSec}s"

function Get-LatestWorkflowStatus([string]$workflowFile) {
    $url = "https://github.com/$owner/$repo/actions/workflows/$workflowFile"
    try {
        $html = (Invoke-WebRequest -Uri $url -UseBasicParsing -ErrorAction Stop).Content
        if ($html -match 'completed successfully') { return 'success' }
        if ($html -match 'failed') { return 'failed' }
        if ($html -match 'in progress' -or $html -match 'nowIn progress') { return 'in_progress' }
        return 'unknown'
    } catch {
        Write-Host "Error fetching workflow page ${workflowFile}: ${_}"
        return 'error'
    }
}

$workflowFiles = @('lucid-unified-build.yml','windows-build.yml','lucid-build.yml')

for ($i = 1; $i -le $maxAttempts; $i++) {
    Write-Host "Attempt $i of $maxAttempts - checking workflows..."
    $allSuccess = $true
    $anyInProgress = $false
    foreach ($wf in $workflowFiles) {
        $status = Get-LatestWorkflowStatus -workflowFile $wf
        Write-Host "  ${wf} -> ${status}"
        if ($status -eq 'failed') {
            Write-Host "  -> Detected failed run for ${wf}. Triggering a re-run via empty commit"
            git commit --allow-empty -m "ci: retry $wf (auto)" | Out-Null
            git push origin main | Out-Null
            $allSuccess = $false
        } elseif ($status -eq 'in_progress') {
            $allSuccess = $false
            $anyInProgress = $true
        } elseif ($status -eq 'unknown' -or $status -eq 'error') {
            $allSuccess = $false
        }
    }
    if ($allSuccess -and -not $anyInProgress) {
        Write-Host "All monitored workflows report success. Exiting monitor."
        exit 0
    }
    if ($i -lt $maxAttempts) {
        Write-Host "Sleeping for $intervalSec seconds before next check..."
        Start-Sleep -Seconds $intervalSec
    }
}

Write-Host "Max attempts reached. Stopping monitor."
exit 2
