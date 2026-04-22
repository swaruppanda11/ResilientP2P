<#
.SYNOPSIS
  Run a short ResilientP2P DHT-primary GKE demo and save a Markdown transcript.

.DESCRIPTION
  This script mirrors the coordinator-primary demo, but targets the DHT-primary
  stack in the p2p-dht namespace.

  It demonstrates:

    1. Cold request: peer-a1 misses cache and fetches from origin.
    2. Same-building request: peer-a2 discovers peer-a1 through DHT-primary discovery.
    3. Cross-building request: peer-b1 also avoids origin through peer reuse.
    4. Local cache request: peer-b1 serves the repeated object locally.
    5. Fallback request: dht-bootstrap is scaled down, then peer-b1 requests a
       warm object that can still be served from peer-a1.

  Output is written to a new Markdown file for demo notes.

.PREREQUISITES
  - kubectl is configured for the GKE cluster.
  - The p2p-dht namespace is deployed and healthy.
  - Local ports 9000, 9001, 9002, and 9003 are free.

.USAGE
  powershell -ExecutionPolicy Bypass -File scripts/demo-dht-cloud.ps1
  powershell -ExecutionPolicy Bypass -File scripts/demo-dht-cloud.ps1 -SkipReset
  powershell -ExecutionPolicy Bypass -File scripts/demo-dht-cloud.ps1 -ObjectId demo-dht-lecture-42
#>

param(
    [string]$Namespace = "p2p-dht",
    [string]$ObjectId = ("demo-dht-lecture-" + (Get-Date -Format "yyyyMMdd-HHmmss")),
    [string]$FallbackObjectId = ("demo-dht-fallback-" + (Get-Date -Format "yyyyMMdd-HHmmss")),
    [string]$ColdObjectId = ("demo-dht-cold-" + (Get-Date -Format "yyyyMMdd-HHmmss")),
    [string]$OutputDir = "demo-outputs",
    [switch]$SkipReset
)

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$OutDirAbs = Join-Path $RepoRoot $OutputDir
New-Item -ItemType Directory -Force -Path $OutDirAbs | Out-Null
$Timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$OutputPath = Join-Path $OutDirAbs "dht-primary-cloud-demo-$Timestamp.md"

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
    $proc = Start-Process -FilePath "kubectl" -ArgumentList $args -NoNewWindow -PassThru -RedirectStandardOutput (Join-Path $OutDirAbs "dht-$Service-pf.out") -RedirectStandardError (Join-Path $OutDirAbs "dht-$Service-pf.err")
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
    Start-PortForward "peer-a1" 9001 7000
    Start-PortForward "peer-a2" 9002 7000
    Start-PortForward "peer-b1" 9003 7000
    Start-PortForward "coordinator" 9000 8000
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
    $result = Invoke-RestMethod -Uri $Url -TimeoutSec 25
    $sw.Stop()

    Add-Line "Response:"
    Add-Line '```json'
    Add-Line ($result | ConvertTo-Json -Depth 8)
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

    Add-Line "# ResilientP2P Short DHT-Primary Cloud Demo"
    Add-Line ""
    $GeneratedAt = Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz"
    Add-Line "**Generated:** $GeneratedAt"
    Add-Line ""
    Add-Line "## Demo Goal"
    Add-Line ""
    Add-Line "This demo shows the DHT-primary architecture running on GKE. It demonstrates origin fetch, DHT-based peer discovery, locality-aware peer reuse, local cache hits, and behavior when the DHT bootstrap service is unavailable."
    Add-Line ""
    Add-Line "## Architecture in One Sentence"
    Add-Line ""
    Add-Line "A DHT-primary peer first checks local cache, then queries the Kademlia DHT for providers, falls back to the coordinator if DHT discovery fails or returns no providers, and finally fetches from origin if no peer can serve the object."
    Add-Line ""
    Add-Line "## Demo Setup"
    Add-Line ""
    Add-Line "- Namespace: $Namespace"
    Add-Line "- Demo object: $ObjectId"
    Add-Line "- Warm fallback object: $FallbackObjectId"
    Add-Line "- Cold object during DHT-bootstrap outage: $ColdObjectId"
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
        Write-Host "Resetting DHT-primary stack for a clean demo..."
        Add-Line ""
        Add-Line "## Clean Start"
        Add-Line ""
        Add-Line "For a repeatable demo, the DHT-primary stack is restarted before requests are issued. This clears peer caches and rebuilds DHT/coordinator state."
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
        Start-Sleep -Seconds 10
    }

    Write-Host "Starting DHT-primary port-forwards..."
    Start-DemoPortForwards
    Start-Sleep -Seconds 3

    Wait-HttpOk "http://localhost:9001/health"
    Wait-HttpOk "http://localhost:9002/health"
    Wait-HttpOk "http://localhost:9003/health"
    Wait-HttpOk "http://localhost:9000/health"

    Add-Line ""
    Add-Line "## Live Request Walkthrough"

    $r1Params = @{
        StepTitle = "Step 1 - Cold object fetch from origin"
        PeerName = "peer-a1 / Building-A"
        Url = "http://localhost:9001/trigger-fetch/$ObjectId"
        ExpectedMeaning = "The object is not cached or advertised yet, so peer-a1 fetches it from the origin. After storing it locally, peer-a1 announces it into the DHT and publishes it to the coordinator fallback index."
    }
    $r1 = Fetch-Object @r1Params

    Start-Sleep -Seconds 2

    $r2Params = @{
        StepTitle = "Step 2 - Same-building DHT peer fetch"
        PeerName = "peer-a2 / Building-A"
        Url = "http://localhost:9002/trigger-fetch/$ObjectId"
        ExpectedMeaning = "peer-a2 asks for the same object. In the DHT-primary path, it queries the DHT first, discovers peer-a1 as a provider, and fetches from a peer instead of the origin."
    }
    $r2 = Fetch-Object @r2Params

    Start-Sleep -Seconds 1

    $r3Params = @{
        StepTitle = "Step 3 - Cross-building DHT peer fetch"
        PeerName = "peer-b1 / Building-B"
        Url = "http://localhost:9003/trigger-fetch/$ObjectId"
        ExpectedMeaning = "peer-b1 is in a different logical building. The DHT still returns campus providers, and the requester selects a peer provider instead of using the origin."
    }
    $r3 = Fetch-Object @r3Params

    $r4Params = @{
        StepTitle = "Step 4 - Local cache hit"
        PeerName = "peer-a1 / Building-A"
        Url = "http://localhost:9001/trigger-fetch/$ObjectId"
        ExpectedMeaning = "peer-a1 requests the same object again. Because peer-a1 fetched and stored the object in Step 1, this request is served directly from its local cache."
    }
    $r4 = Fetch-Object @r4Params

    Add-Line ""
    Add-Line "## Hybrid Fallback Mini-Test"
    Add-Line ""
    Add-Line "This step warms a second object on peer-a1, scales down the DHT bootstrap service, and then asks peer-b1 for that warm object. In the DHT-primary design, coordinator fallback is available when DHT discovery fails or returns no providers. Even if the overlay still has enough state to find the provider, this demonstrates that the system remains available while the DHT bootstrap service is unavailable."

    $warmParams = @{
        StepTitle = "Step 5a - Warm fallback object before DHT-bootstrap outage"
        PeerName = "peer-a1 / Building-A"
        Url = "http://localhost:9001/trigger-fetch/$FallbackObjectId"
        ExpectedMeaning = "This creates a cached provider for the fallback object. peer-a1 stores the object, announces it into the DHT, and publishes it to the coordinator fallback index."
    }
    $warm = Fetch-Object @warmParams

    Start-Sleep -Seconds 4

    Run-Cmd "kubectl scale deployment/dht-bootstrap -n $Namespace --replicas=0" | Out-Null
    Start-Sleep -Seconds 3

    $fallbackParams = @{
        StepTitle = "Step 5b - DHT-bootstrap unavailable, warm object still served by peer"
        PeerName = "peer-b1 / Building-B"
        Url = "http://localhost:9003/trigger-fetch/$FallbackObjectId"
        ExpectedMeaning = "The DHT bootstrap service is unavailable. The request still succeeds from a peer, showing that DHT-primary does not immediately collapse to origin when a discovery component is disrupted."
    }
    $fallback = Fetch-Object @fallbackParams

    $coldParams = @{
        StepTitle = "Step 5c - Cold object during DHT-bootstrap outage"
        PeerName = "peer-b1 / Building-B"
        Url = "http://localhost:9003/trigger-fetch/$ColdObjectId"
        ExpectedMeaning = "This object was never warmed. With no peer provider available, the system correctly falls back to the origin."
    }
    $cold = Fetch-Object @coldParams

    Add-Line ""
    Add-Line "### Optional peer-b1 discovery log excerpt"
    Add-Line ""
    Add-Line "The API response reports source and provider, but it does not expose whether the selected peer came from DHT or coordinator fallback. This log excerpt is included as supporting evidence for DHT lookup and fallback events."
    Run-Cmd "kubectl logs -n $Namespace deployment/peer-b1 --since=3m | Select-String -Pattern '$FallbackObjectId|$ColdObjectId|DHT_LOOKUP|COORDINATOR_FALLBACK'" -AllowFailure | Out-Null

    Run-Cmd "kubectl scale deployment/dht-bootstrap -n $Namespace --replicas=1" | Out-Null
    Run-Cmd "kubectl rollout status deployment/dht-bootstrap -n $Namespace --timeout=90s" | Out-Null
    Start-Sleep -Seconds 5

    Add-Line ""
    Add-Line "## Result Summary"
    Add-Line ""
    Add-Line "| Step | Expected behavior | Actual source | Provider | Service latency |"
    Add-Line "|---|---|---:|---|---:|"
    Add-Line ("| 1 | Cold miss goes to origin | {0} | {1} | {2:N2} ms |" -f $r1.source, $r1.provider, [double]$r1.latency_ms)
    Add-Line ("| 2 | Same-building DHT reuse avoids origin | {0} | {1} | {2:N2} ms |" -f $r2.source, $r2.provider, [double]$r2.latency_ms)
    Add-Line ("| 3 | Cross-building DHT reuse avoids origin | {0} | {1} | {2:N2} ms |" -f $r3.source, $r3.provider, [double]$r3.latency_ms)
    Add-Line ("| 4 | Origin provider repeats request and hits local cache | {0} | {1} | {2:N2} ms |" -f $r4.source, $r4.provider, [double]$r4.latency_ms)
    Add-Line ("| 5b | DHT-bootstrap down, warm object served | {0} | {1} | {2:N2} ms |" -f $fallback.source, $fallback.provider, [double]$fallback.latency_ms)
    Add-Line ("| 5c | Cold object falls back to origin | {0} | {1} | {2:N2} ms |" -f $cold.source, $cold.provider, [double]$cold.latency_ms)

    Add-Line ""
    Add-Line "## Optional Coordinator Snapshot"
    Add-Line ""
    Add-Line "The coordinator is the fallback index in this DHT-primary stack. It is not the primary lookup path, but it receives registrations, heartbeats, and publications so it can be used if DHT discovery fails."
    $stats = Invoke-RestMethod -Uri "http://localhost:9000/stats" -TimeoutSec 10
    Add-Line '```json'
    Add-Line ($stats | ConvertTo-Json -Depth 10)
    Add-Line '```'

    Add-Line ""
    Add-Line "## What To Say During The Demo"
    Add-Line ""
    Add-Line "1. The first request is cold, so it goes to origin and creates the first cached provider."
    Add-Line "2. The second request is the same object from another Building-A peer, and DHT-primary discovery lets it fetch from peer-a1."
    Add-Line "3. The third request shows that another building can also avoid the origin by using a campus peer."
    Add-Line "4. The fourth request repeats on peer-a1 and shows a local cache hit, which is the fastest path."
    Add-Line "5. The final steps disable the DHT bootstrap service. A warm object still comes from a peer, while a never-warmed object correctly falls back to origin."

    Add-Line ""
    Add-Line "## Expected Interpretation"
    Add-Line ""
    Add-Line "- source=origin means external bandwidth was consumed."
    Add-Line "- source=peer means the object was served by another campus peer."
    Add-Line "- source=cache means the object was served locally without network transfer."
    Add-Line "- A warm-object peer response while dht-bootstrap is down demonstrates availability under DHT control-plane disruption."
    Add-Line "- A cold-object origin response during the outage is expected because no peer had that object cached."

    Write-Host ""
    Write-Host "DHT-primary demo complete."
    Write-Host "Markdown transcript written to: $OutputPath"
}
finally {
    Stop-PortForwards
}
