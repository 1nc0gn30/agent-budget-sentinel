"""Circuit Breaker State Machine for Token Spending.

100% Python Standard Library — Zero External Dependencies.
"""

from __future__ import annotations

import collections
import datetime
import enum
import threading
import time
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Optional, Tuple


class BreakerState(str, enum.Enum):
    CLOSED = "CLOSED"      # Normal operation (< 80% limit)
    WARN = "WARN"          # Approaching budget limit (80% - 100%)
    TRIPPED = "TRIPPED"    # Budget ceiling reached or manual kill switch active


@dataclass
class BudgetPolicy:
    """Configurable budget guardrail policies."""
    max_budget_usd: float = 5.00
    warn_threshold_pct: float = 0.80
    velocity_limit_usd_per_min: float = 2.00  # Spike detector: trip if rate exceeds $2/min
    auto_trip_on_estimate: bool = True       # Trip if next request would breach ceiling
    query_token_budget: Optional[int] = None # Maximum allowed tokens per query


class CircuitBreaker:
    """Thread-safe circuit breaker preventing catastrophic agent spending runaway loops."""

    def __init__(self, policy: Optional[BudgetPolicy] = None):
        self.policy = policy or BudgetPolicy()
        self._lock = threading.RLock()
        
        self.state: BreakerState = BreakerState.CLOSED
        self.total_spend_usd: float = 0.0
        self.total_prompt_tokens: int = 0
        self.total_completion_tokens: int = 0
        self.total_requests: int = 0
        self.blocked_requests: int = 0
        
        self.trip_count: int = 0
        self.tripped_at: Optional[str] = None
        self.trip_reason: Optional[str] = None
        
        # Sliding 60-second window for spending velocity checks: (timestamp, cost)
        self._spend_window: Deque[Tuple[float, float]] = collections.deque()
        self._listeners: List[Any] = []

    def add_listener(self, callback: Any) -> None:
        """Register a callback for breaker state transitions."""
        with self._lock:
            if callback not in self._listeners:
                self._listeners.append(callback)

    def _notify(self, event_type: str, data: Dict[str, Any]) -> None:
        """Notify registered listeners outside of critical lock if possible."""
        listeners_copy = list(self._listeners)
        for listener in listeners_copy:
            try:
                listener(event_type, data)
            except Exception:
                pass

    def evaluate_request(self, estimated_cost: Any = 0.0) -> Tuple[bool, BreakerState, str]:
        """Check if an incoming request is permitted under current budget rules."""
        if isinstance(estimated_cost, dict):
            cost_val = float(estimated_cost.get("total_cost", 0.0))
        else:
            cost_val = float(estimated_cost or 0.0)

        with self._lock:
            # 1. Already tripped
            if self.state == BreakerState.TRIPPED:
                self.blocked_requests += 1
                return False, BreakerState.TRIPPED, self.trip_reason or "Budget ceiling reached."

            # 2. Check velocity (runaway loop protection)
            now = time.time()
            self._prune_velocity_window(now)
            current_velocity = sum(c for _, c in self._spend_window)
            if self.policy.velocity_limit_usd_per_min > 0:
                if current_velocity + cost_val > self.policy.velocity_limit_usd_per_min:
                    self._trip_locked(
                        f"Spending velocity limit tripped: ${current_velocity:.4f}/min "
                        f"exceeds ${self.policy.velocity_limit_usd_per_min:.2f}/min ceiling."
                    )
                    self.blocked_requests += 1
                    return False, BreakerState.TRIPPED, self.trip_reason

            # 3. Check cumulative budget ceiling with estimation
            projected = self.total_spend_usd + cost_val
            if projected >= self.policy.max_budget_usd:
                if self.policy.auto_trip_on_estimate:
                    self._trip_locked(
                        f"Cumulative budget breached: projected ${projected:.4f} "
                        f"exceeds limit of ${self.policy.max_budget_usd:.2f}."
                    )
                    self.blocked_requests += 1
                    return False, BreakerState.TRIPPED, self.trip_reason

            # 4. Check warning state
            warn_limit = self.policy.max_budget_usd * self.policy.warn_threshold_pct
            if projected >= warn_limit:
                self.state = BreakerState.WARN
                return True, BreakerState.WARN, f"Approaching budget limit: ${projected:.4f} of ${self.policy.max_budget_usd:.2f}."

            self.state = BreakerState.CLOSED
            return True, BreakerState.CLOSED, "Normal operation."

    def record_spend(
        self,
        cost: Any,
        prompt_tokens: int,
        completion_tokens: int,
        model_name: str = ""
    ) -> BreakerState:
        """Record completed spend and update breaker state."""
        if isinstance(cost, dict):
            cost_val = float(cost.get("total_cost", 0.0))
        else:
            cost_val = float(cost or 0.0)

        event_to_notify = None
        event_data = {}
        
        with self._lock:
            now = time.time()
            self.total_spend_usd = round(self.total_spend_usd + cost_val, 6)
            self.total_prompt_tokens += prompt_tokens
            self.total_completion_tokens += completion_tokens
            self.total_requests += 1
            
            self._spend_window.append((now, cost_val))
            self._prune_velocity_window(now)

            # Check if this spend breaches the max budget
            if self.total_spend_usd >= self.policy.max_budget_usd:
                self._trip_locked(
                    f"Max budget reached: spent ${self.total_spend_usd:.4f} "
                    f"(limit: ${self.policy.max_budget_usd:.2f})."
                )
                event_to_notify = "trip"
                event_data = self.get_status()
            elif self.state == BreakerState.TRIPPED:
                # Already tripped - preserve TRIPPED state
                pass
            elif self.total_spend_usd >= (self.policy.max_budget_usd * self.policy.warn_threshold_pct):
                if self.state != BreakerState.WARN:
                    self.state = BreakerState.WARN
                    event_to_notify = "warn"
                    event_data = self.get_status()
            else:
                self.state = BreakerState.CLOSED

        if event_to_notify:
            self._notify(event_to_notify, event_data)

        return self.state

    def trip(self, reason: str = "Manual operator kill switch triggered.") -> None:
        """Manually trip the circuit breaker."""
        event_data = {}
        with self._lock:
            if self.state == BreakerState.TRIPPED:
                if reason:
                    self.trip_reason = reason
                return
            self._trip_locked(reason)
            event_data = self.get_status()
        self._notify("trip", event_data)

    def _trip_locked(self, reason: str) -> None:
        """Internal lock-held trip implementation."""
        self.state = BreakerState.TRIPPED
        self.trip_count += 1
        self.tripped_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self.trip_reason = reason

    def reset(self, reset_spend: bool = False) -> None:
        """Reset the breaker back to CLOSED state."""
        event_data = {}
        with self._lock:
            self.state = BreakerState.CLOSED
            self.trip_reason = None
            if reset_spend:
                self.total_spend_usd = 0.0
                self.total_prompt_tokens = 0
                self.total_completion_tokens = 0
                self.total_requests = 0
                self.blocked_requests = 0
                self.trip_count = 0
                self.tripped_at = None
                self._spend_window.clear()
            event_data = self.get_status()
        self._notify("reset", event_data)

    def set_budget(self, max_budget_usd: float) -> None:
        """Update maximum budget ceiling."""
        with self._lock:
            self.policy.max_budget_usd = max(0.000001, float(max_budget_usd))
            if self.total_spend_usd < self.policy.max_budget_usd and self.state == BreakerState.TRIPPED:
                # If budget was increased above current spend, restore to CLOSED/WARN
                if self.total_spend_usd >= (self.policy.max_budget_usd * self.policy.warn_threshold_pct):
                    self.state = BreakerState.WARN
                else:
                    self.state = BreakerState.CLOSED
                self.trip_reason = None

    def _prune_velocity_window(self, now: float) -> None:
        """Drop velocity entries older than 60 seconds."""
        cutoff = now - 60.0
        while self._spend_window and self._spend_window[0][0] < cutoff:
            self._spend_window.popleft()

    def get_velocity(self) -> float:
        """Current spend rate in USD per minute."""
        with self._lock:
            self._prune_velocity_window(time.time())
            return round(sum(c for _, c in self._spend_window), 6)

    def get_status(self) -> Dict[str, Any]:
        """Snapshot of current circuit breaker state and metrics."""
        with self._lock:
            pct_used = 0.0
            if self.policy.max_budget_usd > 0:
                pct_used = min(100.0, round((self.total_spend_usd / self.policy.max_budget_usd) * 100.0, 2))
                
            remaining = max(0.0, round(self.policy.max_budget_usd - self.total_spend_usd, 6))

            return {
                "state": self.state.value,
                "current_spend_usd": self.total_spend_usd,
                "max_budget_usd": self.policy.max_budget_usd,
                "remaining_budget_usd": remaining,
                "percentage_used": pct_used,
                "velocity_usd_per_min": self.get_velocity(),
                "velocity_limit_usd_per_min": self.policy.velocity_limit_usd_per_min,
                "total_prompt_tokens": self.total_prompt_tokens,
                "total_completion_tokens": self.total_completion_tokens,
                "total_tokens": self.total_prompt_tokens + self.total_completion_tokens,
                "total_requests": self.total_requests,
                "blocked_requests": self.blocked_requests,
                "trip_count": self.trip_count,
                "tripped_at": self.tripped_at,
                "trip_reason": self.trip_reason,
            }
