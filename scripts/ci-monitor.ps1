# ci-monitor.ps1 - Poll GitHub Actions runs and re-trigger by pushing an empty commit on failure
# Usage: powershell -ExecutionPolicy Bypass -File scripts\ci-monitor.ps1

$owner = 'malithwishwa02-dot'
$repo = 'Lucid'
$maxAttempts = 60
$intervalSec = 60
# Monitor-only mode by default: set to $true to allow auto re-trigger via empty commit
$retrigger = $false

Write-Host "Starting CI monitor for ${owner}/${repo} - maxAttempts=${maxAttempts} interval=${intervalSec}s (retrigger=$retrigger)"

function Get-LatestWorkflowStatus([string]$workflowFile) {
    $url = "https://github.com/$owner/$repo/actions/workflows/$workflowFile"
    try {
        $html = (Invoke-WebRequest -Uri $url -UseBasicParsing -ErrorAction Stop).Content
        if ($html -match 'completed successfully') { return @{ status='success'; runUrl=$null } }
        if ($html -match 'failed') {
            $m = [regex]::Match($html, '/actions/runs/([0-9]+)')
            $runUrl = $null
            if ($m.Success) { $runUrl = "https://github.com/$owner/$repo" + $m.Value }
            return @{ status='failed'; runUrl=$runUrl }
        }
        if ($html -match 'in progress' -or $html -match 'nowIn progress') {
            $m = [regex]::Match($html, '/actions/runs/([0-9]+)')
            $runUrl = $null
            if ($m.Success) { $runUrl = "https://github.com/$owner/$repo" + $m.Value }
            return @{ status='in_progress'; runUrl=$runUrl }
        }
        return @{ status='unknown'; runUrl=$null }
    } catch {
        Write-Host "Error fetching workflow page ${workflowFile}: ${_}"
        return @{ status='error'; runUrl=$null }
    }
}

$workflowFiles = @('lucid-unified-build.yml','windows-build.yml','lucid-build.yml')

for ($i = 1; $i -le $maxAttempts; $i++) {
    Write-Host "Attempt $i of $maxAttempts - checking workflows..."
    $allSuccess = $true
    $anyInProgress = $false
    foreach ($wf in $workflowFiles) {
        $result = Get-LatestWorkflowStatus -workflowFile $wf
        $status = $result.status
        $runUrl = $result.runUrl
        Write-Host "  ${wf} -> ${status} (${runUrl})"
        if ($status -eq 'failed') {
            Write-Host "  -> Detected failed run for ${wf}."
            if ($runUrl) {
                $outfile = "scripts/last_failed_${wf}.html"
                Write-Host "  -> Saving run page to ${outfile}"
                try { Invoke-WebRequest -Uri $runUrl -OutFile $outfile -UseBasicParsing -ErrorAction Stop; Write-Host "  -> Run page saved" } catch { Write-Host "  -> Failed to save run page: $_" }
            }
            if ($retrigger) {
                Write-Host "  -> Re-triggering a re-run via empty commit"
                git commit --allow-empty -m "ci: retry ${wf} (auto)" | Out-Null
                git push origin main | Out-Null
            } else {
                Write-Host "  -> Re-trigger disabled (monitor-only mode)"
            }
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
