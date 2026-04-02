import asyncio
import json
import random
import statistics
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import httpx


DEFAULT_BOOTSTRAP_WAIT_SECONDS = 4.0
SERVICE_CONTROL_TIMEOUT_SECONDS = 60.0
SERVICE_READY_TIMEOUT_SECONDS = 45.0
SERVICE_READY_POLL_SECONDS = 1.0


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
        self.compose_file = (self.spec_path.parent / self.spec.get("compose_file", "../docker-compose.yml")).resolve()
        self.results_dir = (self.spec_path.parent / self.spec.get("results_dir", "results")).resolve()
        self.results_dir.mkdir(parents=True, exist_ok=True)
        self.bootstrap_wait_seconds = float(
            self.spec.get("bootstrap_wait_seconds", DEFAULT_BOOTSTRAP_WAIT_SECONDS)
        )
        self.service_ready_timeout_seconds = float(
            self.spec.get("service_ready_timeout_seconds", SERVICE_READY_TIMEOUT_SECONDS)
        )
        self.default_reset_stack = bool(self.spec.get("reset_stack_before_each_scenario", True))
        self.service_names = self._get_service_names()

    def _get_service_names(self) -> List[str]:
        services = ["coordinator", "origin"]
        for peer_id, peer_info in self.peer_map.items():
            services.append(peer_info.get("service", peer_id))
        return services

    async def run(self) -> None:
        for scenario in self.spec["scenarios"]:
            result = await self.run_scenario(scenario)
            result_path = self.results_dir / f"{self._slugify(scenario['name'])}.json"
            with result_path.open("w", encoding="utf-8") as handle:
                json.dump(result, handle, indent=2)
            print(f"[+] Wrote results to {result_path}")

    async def run_scenario(self, scenario: Dict[str, Any]) -> Dict[str, Any]:
        scenario_name = scenario["name"]
        print(f"\n>>> Running Scenario: {scenario_name}")

        if scenario.get("reset_stack_before", self.default_reset_stack):
            print("[.] Resetting stack before scenario...")
            await self._compose_command(["restart", *self.service_names])
            await asyncio.sleep(float(scenario.get("bootstrap_wait_seconds", self.bootstrap_wait_seconds)))
            await self._wait_for_stack_ready()

        events = self._build_events_for_scenario(scenario)
        event_results: List[Dict[str, Any]] = []
        scenario_start = time.perf_counter()
        async with httpx.AsyncClient(timeout=30.0) as client:
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

    def _build_events_for_scenario(self, scenario: Dict[str, Any]) -> List[Event]:
        if scenario.get("steps"):
            return self._build_explicit_events(scenario["steps"])

        events: List[Event] = []
        rng = random.Random(scenario.get("seed", self.spec.get("seed", 42)))
        for request_profile in scenario.get("requests", []):
            events.extend(self._build_request_events(request_profile, rng))
        for churn_profile in scenario.get("churn", []):
            events.extend(self._build_churn_events(churn_profile, rng))
        return sorted(events, key=lambda item: (item.at_seconds, item.priority))

    def _build_explicit_events(self, steps: Sequence[Dict[str, Any]]) -> List[Event]:
        events: List[Event] = []
        cursor = 0.0
        for step in steps:
            action = step["action"]
            if action == "wait":
                cursor += float(step["seconds"])
                continue

            events.append(
                Event(
                    at_seconds=cursor,
                    priority=self._priority_for_action(action),
                    action=action,
                    payload={key: value for key, value in step.items() if key != "action"},
                )
            )
        return sorted(events, key=lambda item: (item.at_seconds, item.priority))

    def _build_request_events(self, profile: Dict[str, Any], rng: random.Random) -> List[Event]:
        kind = profile["kind"]
        if kind == "random_uniform":
            return self._build_random_uniform_requests(profile, rng)
        if kind == "course_burst":
            return self._build_course_burst_requests(profile, rng)
        raise ValueError(f"Unsupported request profile kind: {kind}")

    def _build_random_uniform_requests(self, profile: Dict[str, Any], rng: random.Random) -> List[Event]:
        start = float(profile.get("start_seconds", 0.0))
        end = float(profile["end_seconds"])
        count = int(profile["count"])
        peers = profile["peers"]
        objects = profile["objects"]

        events: List[Event] = []
        for _ in range(count):
            at_seconds = rng.uniform(start, end)
            peer_id = rng.choice(peers)
            object_id = self._weighted_object_choice(objects, rng)
            events.append(
                Event(
                    at_seconds=at_seconds,
                    priority=self._priority_for_action("fetch"),
                    action="fetch",
                    payload={"peer": peer_id, "object_id": object_id},
                )
            )
        return events

    def _build_course_burst_requests(self, profile: Dict[str, Any], rng: random.Random) -> List[Event]:
        start = float(profile["start_seconds"])
        duration = float(profile["duration_seconds"])
        count = int(profile["count"])
        peers = profile["peers"]
        objects = profile["objects"]

        events: List[Event] = []
        for _ in range(count):
            events.append(
                Event(
                    at_seconds=start + rng.uniform(0.0, duration),
                    priority=self._priority_for_action("fetch"),
                    action="fetch",
                    payload={
                        "peer": rng.choice(peers),
                        "object_id": self._weighted_object_choice(objects, rng),
                    },
                )
            )
        return events

    def _build_churn_events(self, profile: Dict[str, Any], rng: random.Random) -> List[Event]:
        kind = profile["kind"]
        if kind == "independent":
            return self._build_independent_churn(profile, rng)
        if kind == "correlated":
            return self._build_correlated_churn(profile)
        raise ValueError(f"Unsupported churn profile kind: {kind}")

    def _build_independent_churn(self, profile: Dict[str, Any], rng: random.Random) -> List[Event]:
        peers = list(profile["peers"])
        count = min(int(profile["count"]), len(peers))
        start = float(profile["start_seconds"])
        end = float(profile["end_seconds"])
        downtime = float(profile.get("downtime_seconds", 0.0))
        selected_peers = rng.sample(peers, count)

        events: List[Event] = []
        for peer_id in selected_peers:
            down_at = rng.uniform(start, end)
            events.append(
                Event(
                    at_seconds=down_at,
                    priority=self._priority_for_action("kill"),
                    action="kill",
                    payload={"peer": peer_id},
                )
            )
            if downtime > 0:
                events.append(
                    Event(
                        at_seconds=down_at + downtime,
                        priority=self._priority_for_action("restart"),
                        action="restart",
                        payload={"peer": peer_id},
                    )
                )
        return events

    def _build_correlated_churn(self, profile: Dict[str, Any]) -> List[Event]:
        events: List[Event] = []
        for churn_event in profile["events"]:
            at_seconds = float(churn_event["at_seconds"])
            downtime = float(churn_event.get("downtime_seconds", 0.0))
            for peer_id in churn_event["peers"]:
                events.append(
                    Event(
                        at_seconds=at_seconds,
                        priority=self._priority_for_action("kill"),
                        action="kill",
                        payload={"peer": peer_id},
                    )
                )
                if downtime > 0:
                    events.append(
                        Event(
                            at_seconds=at_seconds + downtime,
                            priority=self._priority_for_action("restart"),
                            action="restart",
                            payload={"peer": peer_id},
                        )
                    )
        return events

    async def _sleep_until(self, at_seconds: float, scenario_start: float) -> None:
        elapsed = time.perf_counter() - scenario_start
        remaining = at_seconds - elapsed
        if remaining > 0:
            await asyncio.sleep(remaining)

    async def _execute_event(
        self,
        event: Event,
        client: httpx.AsyncClient,
        scenario_start: float,
    ) -> Optional[Dict[str, Any]]:
        actual_started_seconds = time.perf_counter() - scenario_start
        if event.action == "fetch":
            return await self._execute_fetch(event, client, actual_started_seconds)
        if event.action == "kill":
            return await self._execute_kill(event, client, actual_started_seconds)
        if event.action == "restart":
            return await self._execute_restart(event, actual_started_seconds)
        if event.action == "sleep":
            await asyncio.sleep(float(event.payload["seconds"]))
            return {
                "action": "sleep",
                "scheduled_at_seconds": event.at_seconds,
                "actual_started_seconds": actual_started_seconds,
                "seconds": float(event.payload["seconds"]),
            }
        raise ValueError(f"Unsupported event action: {event.action}")

    async def _execute_fetch(
        self,
        event: Event,
        client: httpx.AsyncClient,
        actual_started_seconds: float,
    ) -> Dict[str, Any]:
        peer_id = event.payload["peer"]
        object_id = event.payload["object_id"]
        peer_url = self.peer_map[peer_id]["url"]
        url = f"{peer_url}/trigger-fetch/{object_id}"
        print(f"[*] t={actual_started_seconds:.2f}s fetch {object_id} via {peer_id}")

        started = time.perf_counter()
        try:
            response = await client.get(url)
            response.raise_for_status()
            payload = response.json()
            observed_latency_ms = (time.perf_counter() - started) * 1000
            return {
                "action": "fetch",
                "peer": peer_id,
                "object_id": object_id,
                "scheduled_at_seconds": event.at_seconds,
                "actual_started_seconds": actual_started_seconds,
                "runner_latency_ms": observed_latency_ms,
                "status": payload.get("status", "unknown"),
                "source": payload.get("source"),
                "provider": payload.get("provider"),
                "candidate_count": payload.get("candidate_count", 0),
                "service_latency_ms": payload.get("latency_ms", 0.0),
                "size": payload.get("size", 0),
            }
        except Exception as exc:
            observed_latency_ms = (time.perf_counter() - started) * 1000
            return {
                "action": "fetch",
                "peer": peer_id,
                "object_id": object_id,
                "scheduled_at_seconds": event.at_seconds,
                "actual_started_seconds": actual_started_seconds,
                "runner_latency_ms": observed_latency_ms,
                "status": "failed",
                "source": "error",
                "provider": None,
                "candidate_count": 0,
                "service_latency_ms": 0.0,
                "size": 0,
                "error": str(exc),
            }

    async def _execute_kill(
        self,
        event: Event,
        client: httpx.AsyncClient,
        actual_started_seconds: float,
    ) -> Dict[str, Any]:
        peer_id = event.payload["peer"]
        peer_url = self.peer_map[peer_id]["url"]
        print(f"[!] t={actual_started_seconds:.2f}s kill {peer_id}")
        try:
            await client.post(f"{peer_url}/suicide")
        except Exception:
            pass
        return {
            "action": "kill",
            "peer": peer_id,
            "scheduled_at_seconds": event.at_seconds,
            "actual_started_seconds": actual_started_seconds,
            "status": "issued",
        }

    async def _execute_restart(self, event: Event, actual_started_seconds: float) -> Dict[str, Any]:
        peer_id = event.payload["peer"]
        service_name = self.peer_map[peer_id].get("service", peer_id)
        print(f"[+] t={actual_started_seconds:.2f}s restart {peer_id}")
        await self._compose_command(["up", "-d", service_name])
        await asyncio.sleep(float(event.payload.get("wait_after_seconds", self.bootstrap_wait_seconds)))
        await self._wait_for_peer_ready(peer_id)
        return {
            "action": "restart",
            "peer": peer_id,
            "service": service_name,
            "scheduled_at_seconds": event.at_seconds,
            "actual_started_seconds": actual_started_seconds,
            "status": "restarted",
        }

    async def _collect_peer_stats(self, client: httpx.AsyncClient) -> Dict[str, Any]:
        stats: Dict[str, Any] = {}
        for peer_id, peer_info in self.peer_map.items():
            try:
                response = await client.get(f"{peer_info['url']}/stats")
                response.raise_for_status()
                stats[peer_id] = response.json()
            except Exception as exc:
                stats[peer_id] = {"status": "unavailable", "error": str(exc)}
        return stats

    async def _collect_coordinator_stats(self, client: httpx.AsyncClient) -> Dict[str, Any]:
        try:
            coordinator_url = self.spec.get("coordinator_url", "http://localhost:8000")
            response = await client.get(f"{coordinator_url}/stats")
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            return {"status": "unavailable", "error": str(exc)}

    async def _compose_command(self, args: List[str]) -> None:
        process = await asyncio.create_subprocess_exec(
            "docker",
            "compose",
            "-f",
            str(self.compose_file),
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            process.communicate(), timeout=SERVICE_CONTROL_TIMEOUT_SECONDS
        )
        if process.returncode != 0:
            raise RuntimeError(
                "docker compose command failed: "
                f"{' '.join(args)}\n"
                f"stdout={stdout.decode().strip()}\n"
                f"stderr={stderr.decode().strip()}"
            )

    async def _wait_for_stack_ready(self) -> None:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await self._wait_for_url(client, self.spec.get("coordinator_url", "http://localhost:8000") + "/health")
            origin_url = self.spec.get("origin_url", "http://localhost:8001")
            await self._wait_for_url(client, f"{origin_url}/health")
            for peer_id in self.peer_map:
                await self._wait_for_peer_ready(peer_id, client=client)

    async def _wait_for_peer_ready(
        self,
        peer_id: str,
        client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        peer_url = self.peer_map[peer_id]["url"]
        owns_client = client is None
        if client is None:
            client = httpx.AsyncClient(timeout=5.0)
        try:
            await self._wait_for_url(client, f"{peer_url}/health")
        finally:
            if owns_client:
                await client.aclose()

    async def _wait_for_url(self, client: httpx.AsyncClient, url: str) -> None:
        deadline = time.perf_counter() + self.service_ready_timeout_seconds
        last_error = "service did not become healthy"
        while time.perf_counter() < deadline:
            try:
                response = await client.get(url)
                response.raise_for_status()
                payload = response.json()
                if payload.get("status") == "ok":
                    return
                last_error = f"unexpected payload: {payload}"
            except Exception as exc:
                last_error = str(exc)
            await asyncio.sleep(SERVICE_READY_POLL_SECONDS)

        raise RuntimeError(f"Timed out waiting for service health at {url}: {last_error}")

    def _summarize_results(self, events: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
        fetches = [event for event in events if event["action"] == "fetch"]
        successes = [event for event in fetches if event["status"] == "success"]
        service_latencies = [event["service_latency_ms"] for event in successes]
        runner_latencies = [event["runner_latency_ms"] for event in successes]

        source_counts: Dict[str, int] = {}
        total_bytes_by_source: Dict[str, int] = {}
        for event in successes:
            source = event.get("source", "unknown")
            source_counts[source] = source_counts.get(source, 0) + 1
            total_bytes_by_source[source] = total_bytes_by_source.get(source, 0) + int(event.get("size", 0))

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
                statistics.mean(event.get("candidate_count", 0) for event in successes)
                if successes else 0.0
            ),
        }

    def _latency_summary(self, latencies: Sequence[float]) -> Dict[str, float]:
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
        fraction = index - lower
        return float(values[lower] + (values[upper] - values[lower]) * fraction)

    def _weighted_object_choice(self, objects: Sequence[Any], rng: random.Random) -> str:
        if not objects:
            raise ValueError("Object list cannot be empty")

        normalized: List[Dict[str, Any]] = []
        for item in objects:
            if isinstance(item, str):
                normalized.append({"id": item, "weight": 1})
            else:
                normalized.append({"id": item["id"], "weight": int(item.get("weight", 1))})

        total_weight = sum(entry["weight"] for entry in normalized)
        threshold = rng.uniform(0, total_weight)
        cumulative = 0.0
        for entry in normalized:
            cumulative += entry["weight"]
            if threshold <= cumulative:
                return entry["id"]
        return normalized[-1]["id"]

    def _priority_for_action(self, action: str) -> int:
        priorities = {"kill": 0, "restart": 1, "fetch": 2, "sleep": 3}
        return priorities.get(action, 99)

    def _slugify(self, name: str) -> str:
        return "".join(character.lower() if character.isalnum() else "-" for character in name).strip("-")


async def main() -> None:
    spec_path = Path(__file__).with_name("workload.json")
    runner = ExperimentRunner(spec_path)
    await runner.run()


if __name__ == "__main__":
    asyncio.run(main())
