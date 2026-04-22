<#
.SYNOPSIS
  Run a short ResilientP2P GKE demo and save a Markdown transcript.

.DESCRIPTION
  This script is designed for a <2 minute class demo. It uses the
  coordinator-primary stack because that path demonstrates the full system
  most clearly:

    1. Cold request: peer-a1 misses cache and fetches from origin.
    2. Same-building request: peer-a2 discovers peer-a1 and fetches from peer.
    3. Cross-building request: peer-b1 fetches the same object from a peer.
    4. Local cache request: peer-b1 requests the object again and serves it locally.
    5. Fallback request: coordinator is scaled down, then peer-b1 requests a
       warm object from peer-a1 through DHT fallback.

  Output is written to a new Markdown file so you can show the transcript or
  use it as speaker notes.

.PREREQUISITES
  - kubectl is configured for the GKE cluster.
  - The p2p-coordinator namespace is deployed and healthy.
  - Local ports 7001, 7002, 7003, and 8000 are free.

.USAGE
  powershell -ExecutionPolicy Bypass -File scripts/demo-coordinator-cloud.ps1
  powershell -ExecutionPolicy Bypass -File scripts/demo-coordinator-cloud.ps1 -SkipReset
  powershell -ExecutionPolicy Bypass -File scripts/demo-coordinator-cloud.ps1 -ObjectId demo-lecture-42
#>

param(
    [string]$Namespace = "p2p-coordinator",
    [string]$ObjectId = ("demo-lecture-" + (Get-Date -Format "yyyyMMdd-HHmmss")),
    [string]$FallbackObjectId = ("demo-fallback-" + (Get-Date -Format "yyyyMMdd-HHmmss")),
    [string]$OutputDir = "demo-outputs",
    [switch]$SkipReset
)

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$OutDirAbs = Join-Path $RepoRoot $OutputDir
New-Item -ItemType Directory -Force -Path $OutDirAbs | Out-Null
$Timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$OutputPath = Join-Path $OutDirAbs "coordinator-cloud-demo-$Timestamp.md"

$PortForwards = @()

function Add-Line {
    param([string]$Text = "")
    Add-Content -Path $OutputPath -Value $Text
}

function Run-Cmd {
    param(
        [string]$Command,
        [switch]$AllowFailure
    )
    Add-Line ""
    Add-Line '```powershell'
    Add-Line $Command
    Add-Line '```'
    $output = Invoke-Expression "$Command 2>&1" | Out-String
    Add-Line '```text'
    Add-Line ($output.TrimEnd())
    Add-Line '```'
    if (-not $AllowFailure -and $LASTEXITCODE -ne 0) {
        throw "Command failed: $Command"
    }
    return $output
}

function Start-PortForward {
    param(
        [string]$Service,
        [int]$LocalPort,
        [int]$RemotePort
    )
    $args = @("port-forward", "-n", $Namespace, "svc/$Service", "${LocalPort}:${RemotePort}")
    $proc = Start-Process -FilePath "kubectl" -ArgumentList $args -NoNewWindow -PassThru -RedirectStandardOutput (Join-Path $OutDirAbs "$Service-pf.out") -RedirectStandardError (Join-Path $OutDirAbs "$Service-pf.err")
    $script:PortForwards += $proc
}

function Stop-PortForwards {
    foreach ($proc in $script:PortForwards) {
        if ($proc -and -not $proc.HasExited) {
            Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
        }
    }
    $script:PortForwards = @()
}

function Start-DemoPortForwards {
    Start-PortForward "peer-a1" 7001 7000
    Start-PortForward "peer-a2" 7002 7000
    Start-PortForward "peer-b1" 7003 7000
    Start-PortForward "coordinator" 8000 8000
}

function Wait-HttpOk {
    param(
        [string]$Url,
        [int]$TimeoutSeconds = 45
    )
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            Invoke-RestMethod -Uri $Url -TimeoutSec 3 | Out-Null
            return
        } catch {
            Start-Sleep -Seconds 1
        }
    }
    throw "Timed out waiting for $Url"
}

function Fetch-Object {
    param(
        [string]$StepTitle,
        [string]$PeerName,
        [string]$Url,
        [string]$ExpectedMeaning
    )

    Add-Line ""
    Add-Line "### $StepTitle"
    Add-Line ""
    Add-Line "**What this demonstrates:** $ExpectedMeaning"
    Add-Line ""
    Add-Line "Request:"
    Add-Line '```text'
    Add-Line "$PeerName -> GET $Url"
    Add-Line '```'

    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    $result = Invoke-RestMethod -Uri $Url -TimeoutSec 20
    $sw.Stop()

    $resultJson = $result | ConvertTo-Json -Depth 8
    Add-Line "Response:"
    Add-Line '```json'
    Add-Line $resultJson
    Add-Line '```'

    Add-Line "Presenter note:"
    Add-Line ("- Source reported by the system: {0}" -f $result.source)
    Add-Line ("- Provider: {0}" -f $result.provider)
    Add-Line ("- Candidate count: {0}" -f $result.candidate_count)
    Add-Line ("- Service latency reported by peer: {0:N2} ms" -f [double]$result.latency_ms)
    Add-Line ("- Wall-clock time observed by script: {0:N2} ms" -f $sw.Elapsed.TotalMilliseconds)

    return $result
}

try {
    Set-Location $RepoRoot

    Add-Line "# ResilientP2P Short Cloud Demo"
    Add-Line ""
    $GeneratedAt = Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz"
    Add-Line "**Generated:** $GeneratedAt"
    Add-Line ""
    Add-Line "## Demo Goal"
    Add-Line ""
    Add-Line "This demo shows the coordinator-primary architecture running on GKE. In under two minutes, it demonstrates origin fetch, peer-assisted cache reuse, locality-aware peer transfer, local cache hits, and hybrid fallback when the coordinator is unavailable."
    Add-Line ""
    Add-Line "## Architecture in One Sentence"
    Add-Line ""
    Add-Line "A peer first checks its local cache, then uses the coordinator to discover nearby providers, falls back to the DHT if the coordinator is unavailable, and finally fetches from the origin if no peer can serve the object."
    Add-Line ""
    Add-Line "## Demo Setup"
    Add-Line ""
    Add-Line "- Namespace: $Namespace"
    Add-Line "- Demo object: $ObjectId"
    Add-Line "- Fallback object: $FallbackObjectId"
    Add-Line "- Peers:"
    Add-Line "  - peer-a1: Building-A"
    Add-Line "  - peer-a2: Building-A"
    Add-Line "  - peer-b1: Building-B"
    Add-Line "- Locality model:"
    Add-Line "  - same building: 5 ms"
    Add-Line "  - cross building: 35 ms"
    Add-Line "  - origin: 120 ms"

    Write-Host "Checking Kubernetes namespace and pods..."
    Run-Cmd "kubectl get pods -n $Namespace -o wide" | Out-Null

    if (-not $SkipReset) {
        Write-Host "Resetting coordinator stack for a clean demo..."
        Add-Line ""
        Add-Line "## Clean Start"
        Add-Line ""
        Add-Line "For a repeatable demo, the stack is restarted before requests are issued. This clears peer caches and coordinator state."
        $deployments = @("coordinator", "origin", "dht-bootstrap", "peer-a1", "peer-a2", "peer-b1")
        foreach ($deployment in $deployments) {
            Run-Cmd "kubectl scale deployment/$deployment -n $Namespace --replicas=0" | Out-Null
        }
        Start-Sleep -Seconds 4
        foreach ($deployment in $deployments) {
            Run-Cmd "kubectl scale deployment/$deployment -n $Namespace --replicas=1" | Out-Null
        }
        foreach ($deployment in $deployments) {
            Run-Cmd "kubectl rollout status deployment/$deployment -n $Namespace --timeout=90s" | Out-Null
        }
        Start-Sleep -Seconds 8
    }

    Write-Host "Starting port-forwards..."
    Start-DemoPortForwards
    Start-Sleep -Seconds 3

    Wait-HttpOk "http://localhost:7001/health"
    Wait-HttpOk "http://localhost:7002/health"
    Wait-HttpOk "http://localhost:7003/health"
    Wait-HttpOk "http://localhost:8000/health"

    Add-Line ""
    Add-Line "## Live Request Walkthrough"

    $r1Params = @{
        StepTitle = "Step 1 - Cold object fetch from origin"
        PeerName = "peer-a1 / Building-A"
        Url = "http://localhost:7001/trigger-fetch/$ObjectId"
        ExpectedMeaning = "The object is not cached anywhere yet, so peer-a1 must fetch it from the origin. After this request, peer-a1 stores it locally and publishes metadata to the coordinator and DHT."
    }
    $r1 = Fetch-Object @r1Params

    Start-Sleep -Seconds 1

    $r2Params = @{
        StepTitle = "Step 2 - Same-building peer fetch"
        PeerName = "peer-a2 / Building-A"
        Url = "http://localhost:7002/trigger-fetch/$ObjectId"
        ExpectedMeaning = "peer-a2 asks for the same object. The coordinator discovers peer-a1 as a provider in the same building, so the object is served by a peer instead of the origin."
    }
    $r2 = Fetch-Object @r2Params

    Start-Sleep -Seconds 1

    $r3Params = @{
        StepTitle = "Step 3 - Cross-building peer fetch"
        PeerName = "peer-b1 / Building-B"
        Url = "http://localhost:7003/trigger-fetch/$ObjectId"
        ExpectedMeaning = "peer-b1 is in a different logical building. The system still avoids the origin by fetching from a peer, but the topology model applies cross-building delay."
    }
    $r3 = Fetch-Object @r3Params

    $r4Params = @{
        StepTitle = "Step 4 - Local cache hit"
        PeerName = "peer-b1 / Building-B"
        Url = "http://localhost:7003/trigger-fetch/$ObjectId"
        ExpectedMeaning = "peer-b1 requests the same object again. This time it serves the object directly from its own local cache, which is the fastest path."
    }
    $r4 = Fetch-Object @r4Params

    Add-Line ""
    Add-Line "## Hybrid Fallback Mini-Test"
    Add-Line ""
    Add-Line "This final step warms a second object on peer-a1, intentionally scales the coordinator down, and then asks peer-b1 for that warm object. A successful peer response while the coordinator is unavailable demonstrates DHT fallback."

    $warmParams = @{
        StepTitle = "Step 5a - Warm fallback object before coordinator failure"
        PeerName = "peer-a1 / Building-A"
        Url = "http://localhost:7001/trigger-fetch/$FallbackObjectId"
        ExpectedMeaning = "This creates a cached provider for the fallback object and gives the DHT time to learn the provider."
    }
    $warm = Fetch-Object @warmParams

    Start-Sleep -Seconds 4

    Run-Cmd "kubectl scale deployment/coordinator -n $Namespace --replicas=0" | Out-Null
    Start-Sleep -Seconds 3

    $fallbackParams = @{
        StepTitle = "Step 5b - Coordinator unavailable, DHT fallback serves warm object"
        PeerName = "peer-b1 / Building-B"
        Url = "http://localhost:7003/trigger-fetch/$FallbackObjectId"
        ExpectedMeaning = "The coordinator is down, so the normal coordinator lookup fails. The peer falls back to the DHT, finds the warm object provider, and fetches from another peer instead of the origin."
    }
    $fallback = Fetch-Object @fallbackParams

    Run-Cmd "kubectl scale deployment/coordinator -n $Namespace --replicas=1" | Out-Null
    Run-Cmd "kubectl rollout status deployment/coordinator -n $Namespace --timeout=90s" | Out-Null
    Start-Sleep -Seconds 3

    Write-Host "Refreshing port-forwards after coordinator restart..."
    Stop-PortForwards
    Start-DemoPortForwards
    Start-Sleep -Seconds 3
    Wait-HttpOk "http://localhost:8000/health"

    Add-Line ""
    Add-Line "## Result Summary"
    Add-Line ""
    Add-Line "| Step | Expected behavior | Actual source | Provider | Service latency |"
    Add-Line "|---|---|---:|---|---:|"
    Add-Line ("| 1 | Cold miss goes to origin | {0} | {1} | {2:N2} ms |" -f $r1.source, $r1.provider, [double]$r1.latency_ms)
    Add-Line ("| 2 | Same-building reuse avoids origin | {0} | {1} | {2:N2} ms |" -f $r2.source, $r2.provider, [double]$r2.latency_ms)
    Add-Line ("| 3 | Cross-building reuse avoids origin | {0} | {1} | {2:N2} ms |" -f $r3.source, $r3.provider, [double]$r3.latency_ms)
    Add-Line ("| 4 | Repeated request hits local cache | {0} | {1} | {2:N2} ms |" -f $r4.source, $r4.provider, [double]$r4.latency_ms)
    Add-Line ("| 5 | Coordinator down, DHT fallback finds peer | {0} | {1} | {2:N2} ms |" -f $fallback.source, $fallback.provider, [double]$fallback.latency_ms)

    Add-Line ""
    Add-Line "## Optional Coordinator Snapshot After Restart"
    Add-Line ""
    Add-Line "This snapshot is optional for the live demo. Because the coordinator was intentionally restarted, its in-memory state may still be rebuilding as peers heartbeat and republish cached objects."
    $stats = Invoke-RestMethod -Uri "http://localhost:8000/stats" -TimeoutSec 10
    Add-Line '```json'
    Add-Line ($stats | ConvertTo-Json -Depth 10)
    Add-Line '```'

    Add-Line ""
    Add-Line "## What To Say During The Demo"
    Add-Line ""
    Add-Line "1. The first request is intentionally cold, so it goes to the origin."
    Add-Line "2. The second request is the same object from another peer in the same building, so it is served by peer-to-peer transfer."
    Add-Line "3. The third request comes from a different building and still avoids the origin, demonstrating campus-wide peer reuse."
    Add-Line "4. The fourth request is served from local cache, showing why repeated campus accesses become very cheap."
    Add-Line "5. Finally, the coordinator is turned off and a warm object is still served from a peer through DHT fallback, showing the hybrid design."

    Add-Line ""
    Add-Line "## Expected Interpretation"
    Add-Line ""
    Add-Line "- source=origin means external bandwidth was consumed."
    Add-Line "- source=peer means the object was served by another campus peer."
    Add-Line "- source=cache means the object was served locally without network transfer."
    Add-Line "- A peer response during coordinator downtime demonstrates hybrid fallback behavior."

    Write-Host ""
    Write-Host "Demo complete."
    Write-Host "Markdown transcript written to: $OutputPath"
}
finally {
    Stop-PortForwards
}
