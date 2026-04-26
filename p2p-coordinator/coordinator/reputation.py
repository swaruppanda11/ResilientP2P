"""Workstream 3 — peer reputation state machine.

In-memory tracker for `healthy → suspect → quarantined → (cooldown) → healthy`.
The store is held by `coordinator.Store`; this module is pure logic so the
unit tests can drive it with an injected clock and no FastAPI surface.

Signal weights (asymmetric per the WS3 plan):
  - metadata_conflict (server-observable)  : 2.0
  - checksum_mismatch (peer-reported)      : 1.0
  - unavailable      (peer-reported, noisy): 0.5

Recovery: a quarantined peer with no new incidents for `cooldown_seconds`
returns to healthy with counters HALVED (not zeroed) so a re-offender hits
suspect immediately. Any incident during cooldown resets the cooldown clock.

Rate limit: a `(reporter, accused, object_id)` triple counts at most once
per `dedupe_window_seconds`. Self-reports are dropped silently.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Dict, Tuple

from common.config import ReputationSettings


# State labels. Strings (not Enum) so they round-trip through Pydantic / JSON
# without ceremony.
HEALTHY = "healthy"
SUSPECT = "suspect"
QUARANTINED = "quarantined"


# Signal -> weight in score points.
SIGNAL_WEIGHTS: Dict[str, float] = {
    "metadata_conflict": 2.0,
    "checksum_mismatch": 1.0,
    "unavailable": 0.5,
}


@dataclass
class PeerReputation:
    peer_id: str
    state: str = HEALTHY
    score: float = 0.0
    checksum_mismatches: int = 0
    unavailable_count: int = 0
    metadata_conflicts: int = 0
    quarantined_at: float | None = None  # monotonic seconds, set on entry

    def to_dict(self) -> dict:
        return {
            "peer_id": self.peer_id,
            "state": self.state,
            "score": round(self.score, 3),
            "checksum_mismatches": self.checksum_mismatches,
            "unavailable_count": self.unavailable_count,
            "metadata_conflicts": self.metadata_conflicts,
            "quarantined_at": self.quarantined_at,
        }


class ReputationTracker:
    """All reputation state for the coordinator.

    A `clock` callable returning seconds (defaults to `time.monotonic`) is
    injectable so tests can advance time without sleeping.
    """

    def __init__(
        self,
        settings: ReputationSettings,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.settings = settings
        self._clock = clock
        self._peers: Dict[str, PeerReputation] = {}
        # (reporter, accused, object_id) -> last_report_monotonic
        self._dedupe: Dict[Tuple[str, str, str], float] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record_incident(
        self,
        accused_peer_id: str,
        reason: str,
        reporter_peer_id: str | None = None,
        object_id: str = "",
    ) -> PeerReputation | None:
        """Record one incident; advance state machine.

        Returns the updated reputation, or None if the report was dropped
        (disabled, exempt peer, self-report, dedupe hit, unknown reason).
        """
        if not self.settings.enabled:
            return None
        if reason not in SIGNAL_WEIGHTS:
            return None
        if accused_peer_id in self.settings.origin_exempt_peer_ids:
            return None
        if reporter_peer_id is not None and reporter_peer_id == accused_peer_id:
            return None  # self-report guard

        if reporter_peer_id is not None:
            key = (reporter_peer_id, accused_peer_id, object_id)
            now = self._clock()
            last = self._dedupe.get(key)
            if last is not None and (now - last) < self.settings.report_dedupe_window_seconds:
                return None
            self._dedupe[key] = now

        rep = self._peers.setdefault(
            accused_peer_id, PeerReputation(peer_id=accused_peer_id)
        )

        # Counter bump.
        if reason == "checksum_mismatch":
            rep.checksum_mismatches += 1
        elif reason == "unavailable":
            rep.unavailable_count += 1
        elif reason == "metadata_conflict":
            rep.metadata_conflicts += 1

        rep.score += SIGNAL_WEIGHTS[reason]

        # Any incident during quarantine resets the cooldown clock.
        if rep.state == QUARANTINED:
            rep.quarantined_at = self._clock()
            return rep

        # State transitions on accumulating score.
        if rep.score >= self.settings.quarantine_threshold:
            rep.state = QUARANTINED
            rep.quarantined_at = self._clock()
        elif rep.score >= self.settings.suspect_threshold:
            rep.state = SUSPECT
        return rep

    def tick_cooldowns(self) -> list[str]:
        """Drive quarantined→healthy transitions when cooldown has elapsed.

        Called periodically (from the coordinator's `periodic_cleanup` task).
        Returns the peer_ids that recovered, for metric emission.
        """
        if not self.settings.enabled:
            return []
        now = self._clock()
        recovered: list[str] = []
        for rep in self._peers.values():
            if rep.state != QUARANTINED or rep.quarantined_at is None:
                continue
            if (now - rep.quarantined_at) >= self.settings.cooldown_seconds:
                # Recover: halve counters (not zero) so re-offender escalates faster.
                rep.state = HEALTHY
                rep.score = rep.score / 2.0
                rep.checksum_mismatches //= 2
                rep.unavailable_count //= 2
                rep.metadata_conflicts //= 2
                rep.quarantined_at = None
                # Re-evaluate against thresholds on the halved score.
                if rep.score >= self.settings.suspect_threshold:
                    rep.state = SUSPECT
                recovered.append(rep.peer_id)
        return recovered

    def state(self, peer_id: str) -> str:
        rep = self._peers.get(peer_id)
        return rep.state if rep else HEALTHY

    def is_quarantined(self, peer_id: str) -> bool:
        return self.state(peer_id) == QUARANTINED

    def is_suspect(self, peer_id: str) -> bool:
        return self.state(peer_id) == SUSPECT

    def get(self, peer_id: str) -> PeerReputation | None:
        return self._peers.get(peer_id)

    def snapshots(self) -> list[PeerReputation]:
        return list(self._peers.values())

    def remove(self, peer_id: str) -> None:
        """Drop reputation when a peer is removed from the registry (cleanup)."""
        self._peers.pop(peer_id, None)
        # Stale dedupe entries age out naturally; no need to scan.
