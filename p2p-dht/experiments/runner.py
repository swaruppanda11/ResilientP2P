"""
Experiment runner for the DHT-primary stack.

Identical in interface to the coordinator-stack runner — it reads the same
workload JSON spec and drives the same fetch / kill / restart events.  The
only differences are:

  1. The default compose file points to ../docker-compose.yml (inside p2p-dht/).
  2. The summary adds DHT-specific metric breakdowns parsed from service logs.

Running:
    cd p2p-dht/experiments
    python runner.py                         # uses workload.json
    python runner.py path/to/spec.json       # custom spec
"""

import asyncio
import json
import os
import random
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence
from urllib.parse import urlparse

import httpx


DEFAULT_BOOTSTRAP_WAIT_SECONDS = 6.0   # slightly longer than coordinator stack
SERVICE_CONTROL_TIMEOUT_SECONDS = 60.0
SERVICE_READY_TIMEOUT_SECONDS = 60.0
SERVICE_READY_POLL_SECONDS = 1.0


class _RunnerAuth(httpx.Auth):
    """Attaches bearer + identity headers on every host-driven request."""

    def __init__(self, token: str, peer_id: str, peer_group: str):
        self._token = token
        self._peer_id = peer_id
        self._peer_group = peer_group

    def auth_flow(self, request):
        if self._token:
            request.headers["Authorization"] = f"Bearer {self._token}"
        if self._peer_id:
            request.headers["X-Peer-Id"] = self._peer_id
        if self._peer_group:
            request.headers["X-Peer-Group"] = self._peer_group
        yield request


def _runner_auth() -> Optional[httpx.Auth]:
    token = os.getenv("AUTH_TOKEN", "")
    if not token:
        return None
    return _RunnerAuth(
        token=token,
        peer_id=os.getenv("RUNNER_PEER_ID", "runner"),
        peer_group=os.getenv("PEER_GROUP", ""),
    )


@dataclass(frozen=True)
class Event:
    at_seconds: float
    priority: int
    action: str
    payload: Dict[str, Any] = field(default_factory=dict)


class ExperimentRunner:
    def __init__(self, spec_path: Path):
        self.spec_path = spec_path.resolve()
        with self.spec_path.open("r", encoding="utf-8") as handle:
            self.spec = json.load(handle)

        self.peer_map: Dict[str, Dict[str, Any]] = self.spec["peer_map"]
        self.orchestrator = self.spec.get("orchestrator", "docker-compose")
        if self.orchestrator not in {"docker-compose", "kubernetes"}:
            raise ValueError(f"Unsupported orchestrator: {self.orchestrator}")
        self.compose_file = (
            self.spec_path.parent / self.spec.get("compose_file", "../docker-compose.yml")
        ).resolve()
        self.namespace = self.spec.get("namespace")
        if self.orchestrator == "kubernetes" and not self.namespace:
            raise ValueError("Kubernetes runner requires 'namespace' in the workload spec")
        self.results_dir = (
            self.spec_path.parent / self.spec.get("results_dir", "results")
        ).resolve()
        self.results_dir.mkdir(parents=True, exist_ok=True)
        self.bootstrap_wait_seconds = float(
            self.spec.get("bootstrap_wait_seconds", DEFAULT_BOOTSTRAP_WAIT_SECONDS)
        )
        self.service_ready_timeout_seconds = float(
            self.spec.get("service_ready_timeout_seconds", SERVICE_READY_TIMEOUT_SECONDS)
        )
        self.default_reset_stack = bool(
            self.spec.get("reset_stack_before_each_scenario", True)
        )
        self.service_names = self._get_service_names()
        self.network_name = f"{self.compose_file.parent.name}_p2p_network"
        self.port_forward_processes: List[subprocess.Popen] = []

    def _get_service_names(self) -> List[str]:
        services = ["coordinator", "origin", "dht-bootstrap"]
        for peer_id, peer_info in self.peer_map.items():
            services.append(peer_info.get("service", peer_id))
        return services

    async def run(self) -> None:
        try:
            await self._preflight_auth_check()
            for scenario in self.spec["scenarios"]:
                result = await self.run_scenario(scenario)
                result_path = self.results_dir / f"{self._slugify(scenario['name'])}.json"
                with result_path.open("w", encoding="utf-8") as handle:
                    json.dump(result, handle, indent=2)
                print(f"[+] Wrote results to {result_path}")
        finally:
            self._stop_port_forwards()

    async def _preflight_auth_check(self) -> None:
        """Probe a gated endpoint once before scenarios.

        If the cluster requires auth but the runner has no AUTH_TOKEN, fail
        loudly here rather than emitting a stream of 401s mid-experiment.
        """
        self._start_port_forwards()
        coord_url = self.spec.get("coordinator_url", "http://localhost:8000")
        try:
            async with httpx.AsyncClient(timeout=5.0, auth=_runner_auth()) as client:
                resp = await client.get(f"{coord_url}/stats")
                if resp.status_code == 401 and not os.getenv("AUTH_TOKEN"):
                    print(
                        "[!] Cluster requires AUTH_TOKEN but runner has none set.\n"
                        "    Export AUTH_TOKEN (and optionally PEER_GROUP) and retry.",
                        file=sys.stderr,
                    )
                    sys.exit(2)
        except httpx.HTTPError:
            return

    async def run_scenario(self, scenario: Dict[str, Any]) -> Dict[str, Any]:
        scenario_name = scenario["name"]
        print(f"\n>>> Running Scenario: {scenario_name}")

        if scenario.get("reset_stack_before", self.default_reset_stack):
            print("[.] Resetting stack before scenario...")
            await self._reset_stack()
            await asyncio.sleep(
                float(scenario.get("bootstrap_wait_seconds", self.bootstrap_wait_seconds))
            )
            await self._wait_for_stack_ready()

        events = self._build_events_for_scenario(scenario)
        event_results: List[Dict[str, Any]] = []
        scenario_start = time.perf_counter()

        async with httpx.AsyncClient(timeout=30.0, auth=_runner_auth()) as client:
            for event in events:
                await self._sleep_until(event.at_seconds, scenario_start)
                result = await self._execute_event(event, client, scenario_start)
                if result is not None:
                    event_results.append(result)

            scenario_duration = time.perf_counter() - scenario_start
            peer_stats = await self._collect_peer_stats(client)
            coordinator_stats = await self._collect_coordinator_stats(client)

        return {
            "scenario": scenario_name,
            "description": scenario.get("description"),
            "topology": self.spec.get("topology", {}),
            "requested_duration_seconds": scenario.get("duration_seconds"),
            "actual_duration_seconds": scenario_duration,
            "event_count": len(events),
            "events": event_results,
            "summary": self._summarize_results(event_results),
            "peer_stats": peer_stats,
            "coordinator_stats": coordinator_stats,
            "generated_from": {
                "request_profiles": scenario.get("requests", []),
                "churn_profiles": scenario.get("churn", []),
                "steps": scenario.get("steps", []),
            },
        }

    # ------------------------------------------------------------------
    # Event building
    # ------------------------------------------------------------------

    def _build_events_for_scenario(self, scenario: Dict[str, Any]) -> List[Event]:
        if scenario.get("steps"):
            return self._build_explicit_events(scenario["steps"])

        events: List[Event] = []
        rng = random.Random(scenario.get("seed", self.spec.get("seed", 42)))
        for profile in scenario.get("requests", []):
            events.extend(self._build_request_events(profile, rng))
        for profile in scenario.get("churn", []):
            events.extend(self._build_churn_events(profile, rng))
        return sorted(events, key=lambda e: (e.at_seconds, e.priority))

    def _build_explicit_events(self, steps: Sequence[Dict[str, Any]]) -> List[Event]:
        events: List[Event] = []
        cursor = 0.0
        for step in steps:
            action = step["action"]
            if action == "wait":
                cursor += float(step["seconds"])
                continue
            events.append(Event(
                at_seconds=cursor,
                priority=self._priority_for_action(action),
                action=action,
                payload={k: v for k, v in step.items() if k != "action"},
            ))
        return sorted(events, key=lambda e: (e.at_seconds, e.priority))

    def _build_request_events(
        self, profile: Dict[str, Any], rng: random.Random
    ) -> List[Event]:
        kind = profile["kind"]
        if kind == "random_uniform":
            return self._build_random_uniform_requests(profile, rng)
        if kind == "course_burst":
            return self._build_course_burst_requests(profile, rng)
        raise ValueError(f"Unsupported request profile kind: {kind}")

    def _build_random_uniform_requests(
        self, profile: Dict[str, Any], rng: random.Random
    ) -> List[Event]:
        start = float(profile.get("start_seconds", 0.0))
        end = float(profile["end_seconds"])
        events: List[Event] = []
        for _ in range(int(profile["count"])):
            events.append(Event(
                at_seconds=rng.uniform(start, end),
                priority=self._priority_for_action("fetch"),
                action="fetch",
                payload={
                    "peer": rng.choice(profile["peers"]),
                    "object_id": self._weighted_object_choice(profile["objects"], rng),
                },
            ))
        return events

    def _build_course_burst_requests(
        self, profile: Dict[str, Any], rng: random.Random
    ) -> List[Event]:
        start = float(profile["start_seconds"])
        duration = float(profile["duration_seconds"])
        events: List[Event] = []
        for _ in range(int(profile["count"])):
            events.append(Event(
                at_seconds=start + rng.uniform(0.0, duration),
                priority=self._priority_for_action("fetch"),
                action="fetch",
                payload={
                    "peer": rng.choice(profile["peers"]),
                    "object_id": self._weighted_object_choice(profile["objects"], rng),
                },
            ))
        return events

    def _build_churn_events(
        self, profile: Dict[str, Any], rng: random.Random
    ) -> List[Event]:
        kind = profile["kind"]
        if kind == "independent":
            return self._build_independent_churn(profile, rng)
        if kind == "correlated":
            return self._build_correlated_churn(profile)
        raise ValueError(f"Unsupported churn profile kind: {kind}")

    def _build_independent_churn(
        self, profile: Dict[str, Any], rng: random.Random
    ) -> List[Event]:
        peers = list(profile["peers"])
        count = min(int(profile["count"]), len(peers))
        start = float(profile["start_seconds"])
        end = float(profile["end_seconds"])
        downtime = float(profile.get("downtime_seconds", 0.0))
        selected = rng.sample(peers, count)
        events: List[Event] = []
        for peer_id in selected:
            down_at = rng.uniform(start, end)
            events.append(Event(
                at_seconds=down_at,
                priority=self._priority_for_action("kill"),
                action="kill",
                payload={"peer": peer_id},
            ))
            if downtime > 0:
                events.append(Event(
                    at_seconds=down_at + downtime,
                    priority=self._priority_for_action("restart"),
                    action="restart",
                    payload={"peer": peer_id},
                ))
        return events

    def _build_correlated_churn(self, profile: Dict[str, Any]) -> List[Event]:
        events: List[Event] = []
        for churn_event in profile["events"]:
            at_seconds = float(churn_event["at_seconds"])
            downtime = float(churn_event.get("downtime_seconds", 0.0))
            for peer_id in churn_event["peers"]:
                events.append(Event(
                    at_seconds=at_seconds,
                    priority=self._priority_for_action("kill"),
                    action="kill",
                    payload={"peer": peer_id},
                ))
                if downtime > 0:
                    events.append(Event(
                        at_seconds=at_seconds + downtime,
                        priority=self._priority_for_action("restart"),
                        action="restart",
                        payload={"peer": peer_id},
                    ))
        return events

    # ------------------------------------------------------------------
    # Event execution
    # ------------------------------------------------------------------

    async def _sleep_until(self, at_seconds: float, scenario_start: float) -> None:
        remaining = at_seconds - (time.perf_counter() - scenario_start)
        if remaining > 0:
            await asyncio.sleep(remaining)

    async def _execute_event(
        self,
        event: Event,
        client: httpx.AsyncClient,
        scenario_start: float,
    ) -> Optional[Dict[str, Any]]:
        actual_started = time.perf_counter() - scenario_start
        if event.action == "fetch":
            return await self._execute_fetch(event, client, actual_started)
        if event.action == "kill":
            return await self._execute_kill(event, client, actual_started)
        if event.action == "restart":
            return await self._execute_restart(event, actual_started)
        if event.action == "disconnect":
            return await self._execute_disconnect(event, actual_started)
        if event.action == "connect":
            return await self._execute_connect(event, actual_started)
        if event.action == "delay":
            return await self._execute_delay(event, actual_started)
        if event.action == "clear_delay":
            return await self._execute_clear_delay(event, actual_started)
        if event.action == "invalidate":
            return await self._execute_invalidate(event, client, actual_started)
        if event.action == "invalidate_prefix":
            return await self._execute_invalidate_prefix(event, client, actual_started)
        if event.action == "revalidate":
            return await self._execute_revalidate(event, client, actual_started)
        if event.action == "sleep":
            await asyncio.sleep(float(event.payload["seconds"]))
            return {
                "action": "sleep",
                "scheduled_at_seconds": event.at_seconds,
                "actual_started_seconds": actual_started,
                "seconds": float(event.payload["seconds"]),
            }
        raise ValueError(f"Unsupported event action: {event.action}")

    async def _execute_fetch(
        self,
        event: Event,
        client: httpx.AsyncClient,
        actual_started: float,
    ) -> Dict[str, Any]:
        peer_id = event.payload["peer"]
        object_id = event.payload["object_id"]
        peer_url = self.peer_map[peer_id]["url"]
        query_params = {
            key: event.payload[key]
            for key in ("version", "cacheability", "max_age_seconds")
            if key in event.payload
        }
        print(f"[*] t={actual_started:.2f}s fetch {object_id} via {peer_id}")

        started = time.perf_counter()
        try:
            response = await client.get(
                f"{peer_url}/trigger-fetch/{object_id}",
                params=query_params,
            )
            response.raise_for_status()
            payload = response.json()
            return {
                "action": "fetch",
                "peer": peer_id,
                "object_id": object_id,
                "scheduled_at_seconds": event.at_seconds,
                "actual_started_seconds": actual_started,
                "runner_latency_ms": (time.perf_counter() - started) * 1000,
                "status": payload.get("status", "unknown"),
                "source": payload.get("source"),
                "provider": payload.get("provider"),
                "candidate_count": payload.get("candidate_count", 0),
                "service_latency_ms": payload.get("latency_ms", 0.0),
                "size": payload.get("size", 0),
                "request_params": query_params,
            }
        except Exception as exc:
            return {
                "action": "fetch",
                "peer": peer_id,
                "object_id": object_id,
                "scheduled_at_seconds": event.at_seconds,
                "actual_started_seconds": actual_started,
                "runner_latency_ms": (time.perf_counter() - started) * 1000,
                "status": "failed",
                "source": "error",
                "provider": None,
                "candidate_count": 0,
                "service_latency_ms": 0.0,
                "size": 0,
                "error": str(exc),
                "request_params": query_params,
            }

    async def _execute_invalidate(
        self,
        event: Event,
        client: httpx.AsyncClient,
        actual_started: float,
    ) -> Dict[str, Any]:
        object_id = event.payload["object_id"]
        print(f"[!] t={actual_started:.2f}s invalidate {object_id}")
        coordinator_url = self.spec.get("coordinator_url", "http://localhost:8000")
        response = await client.post(f"{coordinator_url}/invalidate/{object_id}")
        response.raise_for_status()
        return {
            "action": "invalidate",
            "object_id": object_id,
            "scheduled_at_seconds": event.at_seconds,
            "actual_started_seconds": actual_started,
            "status": "issued",
            "response": response.json(),
        }

    async def _execute_invalidate_prefix(
        self,
        event: Event,
        client: httpx.AsyncClient,
        actual_started: float,
    ) -> Dict[str, Any]:
        prefix = event.payload["prefix"]
        print(f"[!] t={actual_started:.2f}s invalidate prefix {prefix}")
        response = await client.post(
            f"{self.spec.get('coordinator_url', 'http://localhost:8000')}/invalidate-prefix",
            params={"prefix": prefix},
        )
        response.raise_for_status()
        return {
            "action": "invalidate_prefix",
            "prefix": prefix,
            "scheduled_at_seconds": event.at_seconds,
            "actual_started_seconds": actual_started,
            "status": "issued",
            "response": response.json(),
        }

    async def _execute_revalidate(
        self,
        event: Event,
        client: httpx.AsyncClient,
        actual_started: float,
    ) -> Dict[str, Any]:
        object_id = event.payload["object_id"]
        print(f"[!] t={actual_started:.2f}s revalidate {object_id}")
        coordinator_url = self.spec.get("coordinator_url", "http://localhost:8000")
        response = await client.post(f"{coordinator_url}/revalidate/{object_id}")
        response.raise_for_status()
        return {
            "action": "revalidate",
            "object_id": object_id,
            "scheduled_at_seconds": event.at_seconds,
            "actual_started_seconds": actual_started,
            "status": "issued",
            "response": response.json(),
        }

    async def _execute_kill(
        self,
        event: Event,
        client: httpx.AsyncClient,
        actual_started: float,
    ) -> Dict[str, Any]:
        service_name = event.payload.get("service")
        if service_name:
            print(f"[!] t={actual_started:.2f}s stop service {service_name}")
            await self._stop_service(service_name)
            return {
                "action": "kill",
                "service": service_name,
                "scheduled_at_seconds": event.at_seconds,
                "actual_started_seconds": actual_started,
                "status": "stopped",
            }

        peer_id = event.payload["peer"]
        print(f"[!] t={actual_started:.2f}s kill {peer_id}")
        if self.orchestrator == "kubernetes":
            await self._stop_service(self.peer_map[peer_id].get("service", peer_id))
        else:
            peer_url = self.peer_map[peer_id]["url"]
            try:
                await client.post(f"{peer_url}/suicide")
            except Exception:
                pass
        return {
            "action": "kill",
            "peer": peer_id,
            "scheduled_at_seconds": event.at_seconds,
            "actual_started_seconds": actual_started,
            "status": "issued",
        }

    async def _execute_restart(
        self, event: Event, actual_started: float
    ) -> Dict[str, Any]:
        service_name = event.payload.get("service")
        if service_name:
            print(f"[+] t={actual_started:.2f}s restart service {service_name}")
            await self._start_service(service_name)
            await asyncio.sleep(
                float(event.payload.get("wait_after_seconds", self.bootstrap_wait_seconds))
            )
            await self._wait_for_service_ready(service_name)
            return {
                "action": "restart",
                "service": service_name,
                "scheduled_at_seconds": event.at_seconds,
                "actual_started_seconds": actual_started,
                "status": "restarted",
            }

        peer_id = event.payload["peer"]
        service_name = self.peer_map[peer_id].get("service", peer_id)
        print(f"[+] t={actual_started:.2f}s restart {peer_id}")
        await self._start_service(service_name)
        await asyncio.sleep(
            float(event.payload.get("wait_after_seconds", self.bootstrap_wait_seconds))
        )
        await self._wait_for_peer_ready(peer_id)
        return {
            "action": "restart",
            "peer": peer_id,
            "service": service_name,
            "scheduled_at_seconds": event.at_seconds,
            "actual_started_seconds": actual_started,
            "status": "restarted",
        }

    async def _execute_disconnect(
        self, event: Event, actual_started: float
    ) -> Dict[str, Any]:
        service_name = self._resolve_service_name(event.payload)
        print(f"[!] t={actual_started:.2f}s disconnect service {service_name}")
        if self.orchestrator == "kubernetes":
            await self._kubectl_exec(
                service_name,
                ["tc", "qdisc", "replace", "dev", "eth0", "root", "netem", "loss", "100%"],
            )
        else:
            container_id = await self._get_container_id(service_name)
            await self._docker_command(["network", "disconnect", self.network_name, container_id])
        return {
            "action": "disconnect",
            "service": service_name,
            "scheduled_at_seconds": event.at_seconds,
            "actual_started_seconds": actual_started,
            "status": "disconnected",
        }

    async def _execute_connect(
        self, event: Event, actual_started: float
    ) -> Dict[str, Any]:
        service_name = self._resolve_service_name(event.payload)
        print(f"[+] t={actual_started:.2f}s reconnect service {service_name}")
        if self.orchestrator == "kubernetes":
            await self._kubectl_exec(
                service_name,
                ["tc", "qdisc", "del", "dev", "eth0", "root"],
                allow_nonzero=True,
            )
        else:
            container_id = await self._get_container_id(service_name)
            await self._docker_command(["network", "connect", self.network_name, container_id])
        await asyncio.sleep(float(event.payload.get("wait_after_seconds", 2.0)))
        await self._wait_for_service_ready(service_name)
        return {
            "action": "connect",
            "service": service_name,
            "scheduled_at_seconds": event.at_seconds,
            "actual_started_seconds": actual_started,
            "status": "connected",
        }

    async def _execute_delay(
        self, event: Event, actual_started: float
    ) -> Dict[str, Any]:
        service_name = self._resolve_service_name(event.payload)
        delay_ms = int(event.payload["delay_ms"])
        print(f"[!] t={actual_started:.2f}s delay service {service_name} by {delay_ms}ms")
        if self.orchestrator == "kubernetes":
            await self._kubectl_exec(
                service_name,
                ["tc", "qdisc", "replace", "dev", "eth0", "root", "netem", "delay", f"{delay_ms}ms"],
            )
        else:
            container_id = await self._get_container_id(service_name)
            await self._docker_command(
                ["exec", container_id, "tc", "qdisc", "replace", "dev", "eth0", "root", "netem", "delay", f"{delay_ms}ms"]
            )
        return {
            "action": "delay",
            "service": service_name,
            "delay_ms": delay_ms,
            "scheduled_at_seconds": event.at_seconds,
            "actual_started_seconds": actual_started,
            "status": "delayed",
        }

    async def _execute_clear_delay(
        self, event: Event, actual_started: float
    ) -> Dict[str, Any]:
        service_name = self._resolve_service_name(event.payload)
        print(f"[+] t={actual_started:.2f}s clear delay for service {service_name}")
        if self.orchestrator == "kubernetes":
            await self._kubectl_exec(
                service_name,
                ["tc", "qdisc", "del", "dev", "eth0", "root"],
                allow_nonzero=True,
            )
        else:
            container_id = await self._get_container_id(service_name)
            await self._docker_command(
                ["exec", container_id, "tc", "qdisc", "del", "dev", "eth0", "root"],
                allow_nonzero=True,
            )
        return {
            "action": "clear_delay",
            "service": service_name,
            "scheduled_at_seconds": event.at_seconds,
            "actual_started_seconds": actual_started,
            "status": "cleared",
        }

    # ------------------------------------------------------------------
    # Stats collection
    # ------------------------------------------------------------------

    async def _collect_peer_stats(
        self, client: httpx.AsyncClient
    ) -> Dict[str, Any]:
        stats: Dict[str, Any] = {}
        for peer_id, peer_info in self.peer_map.items():
            try:
                response = await client.get(f"{peer_info['url']}/stats")
                response.raise_for_status()
                stats[peer_id] = response.json()
            except Exception as exc:
                stats[peer_id] = {"status": "unavailable", "error": str(exc)}
        return stats

    async def _collect_coordinator_stats(
        self, client: httpx.AsyncClient
    ) -> Dict[str, Any]:
        try:
            coordinator_url = self.spec.get("coordinator_url", "http://localhost:8000")
            response = await client.get(f"{coordinator_url}/stats")
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            return {"status": "unavailable", "error": str(exc)}

    # ------------------------------------------------------------------
    # Docker Compose helpers
    # ------------------------------------------------------------------

    async def _compose_command(self, args: List[str]) -> None:
        await self._docker_command(
            ["compose", "-f", str(self.compose_file), *args],
            timeout=SERVICE_CONTROL_TIMEOUT_SECONDS,
        )

    async def _reset_stack(self) -> None:
        if self.orchestrator == "kubernetes":
            self._stop_port_forwards()
            for service_name in self.service_names:
                await self._stop_service(service_name)
            for service_name in self.service_names:
                await self._start_service(service_name)
            self._start_port_forwards()
            return

        await self._compose_command(["down"])
        await self._compose_command(["up", "-d", *self.service_names])

    async def _stop_service(self, service_name: str) -> None:
        if self.orchestrator == "kubernetes":
            await self._kubectl_scale(service_name, 0)
            self._restart_port_forwards()
            return
        await self._compose_command(["stop", service_name])

    async def _start_service(self, service_name: str) -> None:
        if self.orchestrator == "kubernetes":
            await self._kubectl_scale(service_name, 1)
            await self._kubectl_rollout_status(service_name)
            self._restart_port_forwards()
            return
        await self._compose_command(["up", "-d", service_name])

    async def _docker_command(
        self,
        args: List[str],
        timeout: float = SERVICE_CONTROL_TIMEOUT_SECONDS,
        allow_nonzero: bool = False,
    ) -> str:
        process = await asyncio.create_subprocess_exec(
            "docker",
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        stdout_text = stdout.decode().strip()
        stderr_text = stderr.decode().strip()
        if process.returncode != 0 and not allow_nonzero:
            raise RuntimeError(
                f"docker {' '.join(args)} failed:\n"
                f"stdout={stdout_text}\n"
                f"stderr={stderr_text}"
            )
        return stdout_text

    async def _kubectl_command(
        self,
        args: List[str],
        timeout: float = SERVICE_CONTROL_TIMEOUT_SECONDS,
        allow_nonzero: bool = False,
    ) -> str:
        process = await asyncio.create_subprocess_exec(
            "kubectl",
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        stdout_text = stdout.decode().strip()
        stderr_text = stderr.decode().strip()
        if process.returncode != 0 and not allow_nonzero:
            raise RuntimeError(
                f"kubectl {' '.join(args)} failed:\n"
                f"stdout={stdout_text}\n"
                f"stderr={stderr_text}"
            )
        return stdout_text

    async def _kubectl_scale(self, service_name: str, replicas: int) -> None:
        await self._kubectl_command(
            [
                "scale",
                f"deployment/{service_name}",
                "-n",
                self.namespace,
                f"--replicas={replicas}",
            ]
        )

    async def _kubectl_rollout_status(self, service_name: str) -> None:
        await self._kubectl_command(
            [
                "rollout",
                "status",
                f"deployment/{service_name}",
                "-n",
                self.namespace,
                f"--timeout={int(self.service_ready_timeout_seconds)}s",
            ],
            timeout=self.service_ready_timeout_seconds + 15,
        )

    async def _kubectl_exec(
        self,
        service_name: str,
        command: List[str],
        allow_nonzero: bool = False,
    ) -> str:
        return await self._kubectl_command(
            ["exec", "-n", self.namespace, f"deployment/{service_name}", "--", *command],
            allow_nonzero=allow_nonzero,
        )

    async def _get_container_id(self, service_name: str) -> str:
        output = await self._docker_command(
            ["compose", "-f", str(self.compose_file), "ps", "-q", service_name]
        )
        container_id = output.strip().splitlines()[0] if output.strip() else ""
        if not container_id:
            raise RuntimeError(f"Could not resolve container id for service '{service_name}'")
        return container_id

    async def _wait_for_stack_ready(self) -> None:
        if self.orchestrator == "kubernetes":
            self._start_port_forwards()
        async with httpx.AsyncClient(timeout=5.0, auth=_runner_auth()) as client:
            coordinator_url = self.spec.get("coordinator_url", "http://localhost:8000")
            origin_url = self.spec.get("origin_url", "http://localhost:8001")
            await self._wait_for_url(client, f"{coordinator_url}/health")
            await self._wait_for_url(client, f"{origin_url}/health")
            for peer_id in self.peer_map:
                await self._wait_for_peer_ready(peer_id, client=client)

    def _restart_port_forwards(self) -> None:
        if self.orchestrator != "kubernetes":
            return
        self._stop_port_forwards()
        self._start_port_forwards()

    def _start_port_forwards(self) -> None:
        if self.orchestrator != "kubernetes":
            return
        if any(process.poll() is None for process in self.port_forward_processes):
            return

        forwards = [
            ("coordinator", self._local_port_from_url(self.spec.get("coordinator_url", "http://localhost:8000")), 8000),
            ("origin", self._local_port_from_url(self.spec.get("origin_url", "http://localhost:8001")), 8001),
        ]
        for peer_id, peer_info in self.peer_map.items():
            forwards.append((peer_info.get("service", peer_id), self._local_port_from_url(peer_info["url"]), 7000))

        self.port_forward_processes = []
        for service_name, local_port, remote_port in forwards:
            process = subprocess.Popen(
                [
                    "kubectl",
                    "port-forward",
                    "-n",
                    self.namespace,
                    f"svc/{service_name}",
                    f"{local_port}:{remote_port}",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self.port_forward_processes.append(process)
        time.sleep(2.0)

    def _stop_port_forwards(self) -> None:
        for process in self.port_forward_processes:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
        self.port_forward_processes = []

    def _local_port_from_url(self, url: str) -> int:
        parsed = urlparse(url)
        if parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1"} or parsed.port is None:
            raise ValueError(f"Kubernetes runner expects localhost URL, got: {url}")
        return parsed.port

    async def _wait_for_service_ready(self, service_name: str) -> None:
        health_url = self._service_health_url(service_name)
        if health_url is None:
            return
        async with httpx.AsyncClient(timeout=5.0, auth=_runner_auth()) as client:
            await self._wait_for_url(client, health_url)

    def _service_health_url(self, service_name: str) -> Optional[str]:
        if service_name == "coordinator":
            return self.spec.get("coordinator_url", "http://localhost:8000") + "/health"
        if service_name == "origin":
            return self.spec.get("origin_url", "http://localhost:8001") + "/health"
        if service_name == "dht-bootstrap":
            return None
        return None

    async def _wait_for_peer_ready(
        self,
        peer_id: str,
        client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        peer_url = self.peer_map[peer_id]["url"]
        owns_client = client is None
        if client is None:
            client = httpx.AsyncClient(timeout=5.0, auth=_runner_auth())
        try:
            await self._wait_for_url(client, f"{peer_url}/health")
        finally:
            if owns_client:
                await client.aclose()

    async def _wait_for_url(
        self, client: httpx.AsyncClient, url: str
    ) -> None:
        deadline = time.perf_counter() + self.service_ready_timeout_seconds
        last_error = "service did not become healthy"
        while time.perf_counter() < deadline:
            try:
                response = await client.get(url)
                response.raise_for_status()
                if response.json().get("status") == "ok":
                    return
                last_error = f"unexpected payload: {response.json()}"
            except Exception as exc:
                last_error = str(exc)
            await asyncio.sleep(SERVICE_READY_POLL_SECONDS)
        raise RuntimeError(
            f"Timed out waiting for service at {url}: {last_error}"
        )

    # ------------------------------------------------------------------
    # Result summarisation
    # ------------------------------------------------------------------

    def _summarize_results(
        self, events: Sequence[Dict[str, Any]]
    ) -> Dict[str, Any]:
        fetches = [e for e in events if e["action"] == "fetch"]
        successes = [e for e in fetches if e["status"] == "success"]
        service_latencies = [e["service_latency_ms"] for e in successes]
        runner_latencies = [e["runner_latency_ms"] for e in successes]

        source_counts: Dict[str, int] = {}
        total_bytes_by_source: Dict[str, int] = {}
        for e in successes:
            src = e.get("source", "unknown")
            source_counts[src] = source_counts.get(src, 0) + 1
            total_bytes_by_source[src] = (
                total_bytes_by_source.get(src, 0) + int(e.get("size", 0))
            )

        return {
            "total_events": len(events),
            "fetch_count": len(fetches),
            "successful_fetch_count": len(successes),
            "failed_fetch_count": len(fetches) - len(successes),
            "success_rate": (len(successes) / len(fetches)) if fetches else 0.0,
            "source_counts": source_counts,
            "bytes_by_source": total_bytes_by_source,
            "service_latency_ms": self._latency_summary(service_latencies),
            "runner_latency_ms": self._latency_summary(runner_latencies),
            "average_candidate_count": (
                statistics.mean(e.get("candidate_count", 0) for e in successes)
                if successes else 0.0
            ),
        }

    def _latency_summary(
        self, latencies: Sequence[float]
    ) -> Dict[str, float]:
        if not latencies:
            return {"min": 0.0, "mean": 0.0, "median": 0.0, "p95": 0.0, "max": 0.0}
        ordered = sorted(latencies)
        return {
            "min": min(ordered),
            "mean": statistics.mean(ordered),
            "median": statistics.median(ordered),
            "p95": self._percentile(ordered, 95),
            "max": max(ordered),
        }

    def _percentile(self, values: Sequence[float], percentile: int) -> float:
        if not values:
            return 0.0
        if len(values) == 1:
            return float(values[0])
        index = (len(values) - 1) * (percentile / 100)
        lower = int(index)
        upper = min(lower + 1, len(values) - 1)
        if lower == upper:
            return float(values[lower])
        return float(values[lower] + (values[upper] - values[lower]) * (index - lower))

    def _weighted_object_choice(
        self, objects: Sequence[Any], rng: random.Random
    ) -> str:
        if not objects:
            raise ValueError("Object list cannot be empty")
        normalized = [
            {"id": item, "weight": 1} if isinstance(item, str)
            else {"id": item["id"], "weight": int(item.get("weight", 1))}
            for item in objects
        ]
        total = sum(e["weight"] for e in normalized)
        threshold = rng.uniform(0, total)
        cumulative = 0.0
        for entry in normalized:
            cumulative += entry["weight"]
            if threshold <= cumulative:
                return entry["id"]
        return normalized[-1]["id"]

    def _priority_for_action(self, action: str) -> int:
        return {
            "kill": 0,
            "disconnect": 0,
            "delay": 0,
            "restart": 1,
            "connect": 1,
            "clear_delay": 1,
            "invalidate": 1,
            "invalidate_prefix": 1,
            "revalidate": 1,
            "fetch": 2,
            "sleep": 3,
        }.get(action, 99)

    def _resolve_service_name(self, payload: Dict[str, Any]) -> str:
        service_name = payload.get("service")
        if service_name:
            return service_name
        peer_id = payload.get("peer")
        if peer_id:
            return self.peer_map[peer_id].get("service", peer_id)
        raise ValueError("Event payload must include either 'service' or 'peer'")

    def _slugify(self, name: str) -> str:
        return "".join(
            c.lower() if c.isalnum() else "-" for c in name
        ).strip("-")


async def main() -> None:
    spec_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).with_name("workload.json")
    runner = ExperimentRunner(spec_path)
    await runner.run()


if __name__ == "__main__":
    asyncio.run(main())
