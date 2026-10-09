"""SQLite Persistence and SSE Broadcast Engine.

100% Python Standard Library — Zero External Dependencies.
"""

from __future__ import annotations

import datetime
import json
import queue
import sqlite3
import threading
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class TransactionRecord:
    id: Optional[int]
    timestamp: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    latency_ms: float
    status_code: int
    path: str
    source_ip: str
    tripped: bool
    reason: Optional[str] = None


class BudgetStorage:
    """Thread-safe SQLite store for spending ledger and SSE events."""

    def __init__(self, db_path: str = "budget.db"):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._sse_queues: List[queue.Queue] = []
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def _init_db(self) -> None:
        with self._lock:
            conn = self._get_connection()
            try:
                with conn:
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS settings (
                            key TEXT PRIMARY KEY,
                            value TEXT NOT NULL
                        );
                    """)
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS transactions (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            timestamp TEXT NOT NULL,
                            model TEXT NOT NULL,
                            prompt_tokens INTEGER NOT NULL,
                            completion_tokens INTEGER NOT NULL,
                            cost_usd REAL NOT NULL,
                            latency_ms REAL NOT NULL,
                            status_code INTEGER NOT NULL,
                            path TEXT NOT NULL,
                            source_ip TEXT NOT NULL,
                            tripped INTEGER NOT NULL,
                            reason TEXT
                        );
                    """)
                    conn.execute("""
                        CREATE INDEX IF NOT EXISTS idx_transactions_ts ON transactions(timestamp);
                    """)
                    conn.execute("""
                        CREATE INDEX IF NOT EXISTS idx_transactions_model ON transactions(model);
                    """)
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS events (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            timestamp TEXT NOT NULL,
                            event_type TEXT NOT NULL,
                            message TEXT NOT NULL,
                            data_json TEXT
                        );
                    """)
            finally:
                conn.close()

    def record_transaction(self, record: TransactionRecord) -> int:
        """Insert transaction and broadcast to SSE streams."""
        now_iso = record.timestamp or datetime.datetime.now(datetime.timezone.utc).isoformat()
        with self._lock:
            conn = self._get_connection()
            try:
                with conn:
                    cur = conn.execute("""
                        INSERT INTO transactions (
                            timestamp, model, prompt_tokens, completion_tokens,
                            cost_usd, latency_ms, status_code, path, source_ip,
                            tripped, reason
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        now_iso, record.model, record.prompt_tokens, record.completion_tokens,
                        record.cost_usd, record.latency_ms, record.status_code, record.path,
                        record.source_ip, 1 if record.tripped else 0, record.reason
                    ))
                    inserted_id = cur.lastrowid
            finally:
                conn.close()

        record.id = inserted_id
        # Broadcast via SSE
        self.broadcast_event("transaction", asdict(record))
        return inserted_id

    def record_event(self, event_type: str, message: str, data: Optional[Dict[str, Any]] = None) -> None:
        """Store system audit event."""
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        data_str = json.dumps(data or {})
        with self._lock:
            conn = self._get_connection()
            try:
                with conn:
                    conn.execute("""
                        INSERT INTO events (timestamp, event_type, message, data_json)
                        VALUES (?, ?, ?, ?)
                    """, (now_iso, event_type, message, data_str))
            finally:
                conn.close()

        self.broadcast_event(event_type, {
            "timestamp": now_iso,
            "message": message,
            "data": data or {}
        })

    def get_recent_transactions(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Retrieve recent transactions in descending order."""
        with self._lock:
            conn = self._get_connection()
            try:
                cur = conn.execute("""
                    SELECT id, timestamp, model, prompt_tokens, completion_tokens,
                           cost_usd, latency_ms, status_code, path, source_ip,
                           tripped, reason
                    FROM transactions
                    ORDER BY id DESC LIMIT ?
                """, (limit,))
                rows = cur.fetchall()
                return [dict(r) for r in rows]
            finally:
                conn.close()

    def get_model_breakdown(self) -> List[Dict[str, Any]]:
        """Aggregate total spend and tokens per model."""
        with self._lock:
            conn = self._get_connection()
            try:
                cur = conn.execute("""
                    SELECT model,
                           COUNT(*) as request_count,
                           SUM(prompt_tokens) as total_prompt_tokens,
                           SUM(completion_tokens) as total_completion_tokens,
                           SUM(cost_usd) as total_cost_usd
                    FROM transactions
                    WHERE tripped = 0
                    GROUP BY model
                    ORDER BY total_cost_usd DESC
                """)
                rows = cur.fetchall()
                return [
                    {
                        "model": r["model"] or "unknown",
                        "request_count": r["request_count"],
                        "total_prompt_tokens": r["total_prompt_tokens"] or 0,
                        "total_completion_tokens": r["total_completion_tokens"] or 0,
                        "total_cost_usd": round(r["total_cost_usd"] or 0.0, 6)
                    }
                    for r in rows
                ]
            finally:
                conn.close()

    def get_hourly_spend(self, limit_hours: int = 24) -> List[Dict[str, Any]]:
        """Return spending aggregated by hour for charting."""
        with self._lock:
            conn = self._get_connection()
            try:
                cur = conn.execute("""
                    SELECT strftime('%Y-%m-%dT%H:00:00Z', timestamp) as hour_bucket,
                           SUM(cost_usd) as spend,
                           SUM(prompt_tokens + completion_tokens) as tokens,
                           COUNT(*) as requests
                    FROM transactions
                    WHERE tripped = 0
                    GROUP BY hour_bucket
                    ORDER BY hour_bucket DESC
                    LIMIT ?
                """, (limit_hours,))
                rows = cur.fetchall()
                return [dict(r) for r in reversed(rows)]
            finally:
                conn.close()

    def clear_history(self) -> None:
        """Purge historical transactions."""
        with self._lock:
            conn = self._get_connection()
            try:
                with conn:
                    conn.execute("DELETE FROM transactions;")
                    conn.execute("DELETE FROM events;")
            finally:
                conn.close()

    # --- SSE PubSub ---
    def subscribe_sse(self) -> queue.Queue:
        """Register a new SSE stream queue."""
        q: queue.Queue = queue.Queue(maxsize=100)
        with self._lock:
            self._sse_queues.append(q)
        return q

    def unsubscribe_sse(self, q: queue.Queue) -> None:
        """Unregister an SSE stream queue."""
        with self._lock:
            if q in self._sse_queues:
                self._sse_queues.remove(q)

    def broadcast_event(self, event_name: str, payload: Dict[str, Any]) -> None:
        """Send event to all connected SSE clients."""
        with self._lock:
            queues = list(self._sse_queues)
        
        msg = f"event: {event_name}\ndata: {json.dumps(payload)}\n\n"
        for q in queues:
            try:
                q.put_nowait(msg)
            except queue.Full:
                pass
