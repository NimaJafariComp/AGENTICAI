from __future__ import annotations

import json
import sqlite3
from datetime import datetime, UTC
from pathlib import Path
from typing import Any

import yaml

from backend.schemas import (
    AppSeedData,
    Customer,
    CustomerSeedData,
    CreateRuntimeFinalDecisionInput,
    CreateRuntimeSessionInput,
    CreateRuntimeToolCallInput,
    CreateRuntimeTraceInput,
    DataSummary,
    Order,
    OrderSeedData,
    RefundPolicyDocument,
    PolicyFrontMatter,
    RuntimeFinalDecision,
    RuntimeSession,
    RuntimeToolCall,
    RuntimeTrace,
)


class DataStoreError(RuntimeError):
    """Raised when seed or runtime store operations fail."""


class DataStore:
    def __init__(
        self,
        data_dir: str | Path | None = None,
        runtime_db_path: str | Path | None = None,
    ) -> None:
        project_root = Path(__file__).resolve().parent.parent
        self.data_dir = Path(data_dir) if data_dir else project_root / "data"
        self.runtime_db_path = (
            Path(runtime_db_path) if runtime_db_path else self.data_dir / "runtime.db"
        )

        self.customers_path = self.data_dir / "customers.json"
        self.orders_path = self.data_dir / "orders.json"
        self.policy_path = self.data_dir / "refund_policy.md"

    def load_seed_data(self) -> AppSeedData:
        customers = self.load_customers()
        orders = self.load_orders()
        policy = self.load_policy()
        return AppSeedData(customers=customers, orders=orders, policy=policy)

    def load_customers(self) -> list[Customer]:
        payload = self._read_json(self.customers_path)
        return CustomerSeedData.model_validate(payload).customers

    def load_orders(self) -> list[Order]:
        payload = self._read_json(self.orders_path)
        return OrderSeedData.model_validate(payload).orders

    def load_policy(self) -> RefundPolicyDocument:
        raw = self._read_text(self.policy_path)
        metadata, body = self._parse_front_matter(raw)
        return RefundPolicyDocument(
            metadata=PolicyFrontMatter.model_validate(metadata),
            markdown_body=body.strip(),
        )

    def get_customer_by_id(self, customer_id: str) -> Customer | None:
        return next((customer for customer in self.load_customers() if customer.id == customer_id), None)

    def get_customer_by_email(self, email: str) -> Customer | None:
        normalized = email.strip().lower()
        return next(
            (customer for customer in self.load_customers() if customer.email.lower() == normalized),
            None,
        )

    def get_order_by_id(self, order_id: str) -> Order | None:
        return next((order for order in self.load_orders() if order.id == order_id), None)

    def get_order_item(self, order_id: str, item_id: str):
        order = self.get_order_by_id(order_id)
        if order is None:
            return None
        return next((item for item in order.items if item.item_id == item_id), None)

    def list_orders_for_customer(self, customer_id: str) -> list[Order]:
        return [order for order in self.load_orders() if order.customer_id == customer_id]

    def summary(self) -> DataSummary:
        seed = self.load_seed_data()
        return DataSummary(
            customer_count=len(seed.customers),
            order_count=len(seed.orders),
            policy_name=seed.policy.metadata.policy_name,
            policy_version=seed.policy.metadata.policy_version,
        )

    def init_runtime_db(self) -> None:
        self.runtime_db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect_runtime_db() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    customer_email TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS traces (
                    trace_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS tool_calls (
                    tool_call_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    tool_input_json TEXT NOT NULL,
                    tool_output_json TEXT,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS final_decisions (
                    decision_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    decision_type TEXT NOT NULL,
                    used INTEGER NOT NULL DEFAULT 0,
                    request_fingerprint TEXT NOT NULL,
                    reason_codes_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    used_at TEXT
                );
                """
            )

    def runtime_table_counts(self) -> dict[str, int]:
        with self._connect_runtime_db() as connection:
            tables = ("sessions", "traces", "tool_calls", "final_decisions")
            counts = {}
            for table in tables:
                row = connection.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()
                counts[table] = int(row["count"])
            return counts

    def create_session(self, payload: CreateRuntimeSessionInput) -> RuntimeSession:
        timestamp = self._utc_now()
        with self._connect_runtime_db() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO sessions (session_id, customer_email, created_at, updated_at)
                VALUES (
                    ?,
                    ?,
                    COALESCE((SELECT created_at FROM sessions WHERE session_id = ?), ?),
                    ?
                )
                """,
                (
                    payload.session_id,
                    payload.customer_email,
                    payload.session_id,
                    timestamp,
                    timestamp,
                ),
            )

        return self.get_session(payload.session_id)

    def get_session(self, session_id: str) -> RuntimeSession:
        with self._connect_runtime_db() as connection:
            row = connection.execute(
                """
                SELECT session_id, customer_email, created_at, updated_at
                FROM sessions
                WHERE session_id = ?
                """,
                (session_id,),
            ).fetchone()

        if row is None:
            raise DataStoreError(f"Session not found: {session_id}")

        return RuntimeSession(
            session_id=row["session_id"],
            customer_email=row["customer_email"],
            created_at=self._parse_timestamp(row["created_at"]),
            updated_at=self._parse_timestamp(row["updated_at"]),
        )

    def list_traces(self, session_id: str | None = None) -> list[RuntimeTrace]:
        query = """
            SELECT trace_id, session_id, event_type, payload_json, created_at
            FROM traces
        """
        params: tuple[Any, ...] = ()
        if session_id is not None:
            query += " WHERE session_id = ?"
            params = (session_id,)
        query += " ORDER BY created_at ASC"

        with self._connect_runtime_db() as connection:
            rows = connection.execute(query, params).fetchall()

        return [
            RuntimeTrace(
                trace_id=row["trace_id"],
                session_id=row["session_id"],
                event_type=row["event_type"],
                payload_json=row["payload_json"],
                created_at=self._parse_timestamp(row["created_at"]),
            )
            for row in rows
        ]

    def append_trace(self, payload: CreateRuntimeTraceInput) -> RuntimeTrace:
        timestamp = self._utc_now()
        serialized_payload = self._serialize_json(payload.payload)

        with self._connect_runtime_db() as connection:
            connection.execute(
                """
                INSERT INTO traces (trace_id, session_id, event_type, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    payload.trace_id,
                    payload.session_id,
                    payload.event_type,
                    serialized_payload,
                    timestamp,
                ),
            )

        return RuntimeTrace(
            trace_id=payload.trace_id,
            session_id=payload.session_id,
            event_type=payload.event_type,
            payload_json=serialized_payload,
            created_at=self._parse_timestamp(timestamp),
        )

    def list_tool_calls(self, session_id: str | None = None) -> list[RuntimeToolCall]:
        query = """
            SELECT tool_call_id, session_id, tool_name, tool_input_json, tool_output_json, status, created_at
            FROM tool_calls
        """
        params: tuple[Any, ...] = ()
        if session_id is not None:
            query += " WHERE session_id = ?"
            params = (session_id,)
        query += " ORDER BY created_at ASC"

        with self._connect_runtime_db() as connection:
            rows = connection.execute(query, params).fetchall()

        return [
            RuntimeToolCall(
                tool_call_id=row["tool_call_id"],
                session_id=row["session_id"],
                tool_name=row["tool_name"],
                tool_input_json=row["tool_input_json"],
                tool_output_json=row["tool_output_json"],
                status=row["status"],
                created_at=self._parse_timestamp(row["created_at"]),
            )
            for row in rows
        ]

    def create_tool_call(self, payload: CreateRuntimeToolCallInput) -> RuntimeToolCall:
        timestamp = self._utc_now()
        serialized_input = self._serialize_json(payload.tool_input)
        serialized_output = self._serialize_json(payload.tool_output)

        with self._connect_runtime_db() as connection:
            connection.execute(
                """
                INSERT INTO tool_calls (
                    tool_call_id, session_id, tool_name, tool_input_json, tool_output_json, status, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload.tool_call_id,
                    payload.session_id,
                    payload.tool_name,
                    serialized_input,
                    serialized_output,
                    payload.status,
                    timestamp,
                ),
            )

        return RuntimeToolCall(
            tool_call_id=payload.tool_call_id,
            session_id=payload.session_id,
            tool_name=payload.tool_name,
            tool_input_json=serialized_input,
            tool_output_json=serialized_output,
            status=payload.status,
            created_at=self._parse_timestamp(timestamp),
        )

    def list_final_decisions(self, session_id: str | None = None) -> list[RuntimeFinalDecision]:
        query = """
            SELECT decision_id, session_id, decision_type, used, request_fingerprint,
                   reason_codes_json, created_at, used_at
            FROM final_decisions
        """
        params: tuple[Any, ...] = ()
        if session_id is not None:
            query += " WHERE session_id = ?"
            params = (session_id,)
        query += " ORDER BY created_at ASC"

        with self._connect_runtime_db() as connection:
            rows = connection.execute(query, params).fetchall()

        return [self._runtime_final_decision_from_row(row) for row in rows]

    def create_final_decision(
        self, payload: CreateRuntimeFinalDecisionInput
    ) -> RuntimeFinalDecision:
        timestamp = self._utc_now()
        serialized_reason_codes = self._serialize_json(payload.reason_codes)

        with self._connect_runtime_db() as connection:
            connection.execute(
                """
                INSERT INTO final_decisions (
                    decision_id, session_id, decision_type, used,
                    request_fingerprint, reason_codes_json, created_at, used_at
                )
                VALUES (?, ?, ?, 0, ?, ?, ?, NULL)
                """,
                (
                    payload.decision_id,
                    payload.session_id,
                    payload.decision_type.value,
                    payload.request_fingerprint,
                    serialized_reason_codes,
                    timestamp,
                ),
            )

        return self.get_final_decision(payload.decision_id)

    def get_final_decision(self, decision_id: str) -> RuntimeFinalDecision:
        with self._connect_runtime_db() as connection:
            row = connection.execute(
                """
                SELECT decision_id, session_id, decision_type, used, request_fingerprint,
                       reason_codes_json, created_at, used_at
                FROM final_decisions
                WHERE decision_id = ?
                """,
                (decision_id,),
            ).fetchone()

        if row is None:
            raise DataStoreError(f"Final decision not found: {decision_id}")

        return self._runtime_final_decision_from_row(row)

    def _connect_runtime_db(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.runtime_db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _runtime_final_decision_from_row(self, row: sqlite3.Row) -> RuntimeFinalDecision:
        return RuntimeFinalDecision(
            decision_id=row["decision_id"],
            session_id=row["session_id"],
            decision_type=row["decision_type"],
            used=bool(row["used"]),
            request_fingerprint=row["request_fingerprint"],
            reason_codes_json=row["reason_codes_json"],
            created_at=self._parse_timestamp(row["created_at"]),
            used_at=self._parse_timestamp(row["used_at"]) if row["used_at"] else None,
        )

    def _read_json(self, path: Path) -> dict[str, Any]:
        try:
            with path.open("r", encoding="utf-8") as handle:
                return json.load(handle)
        except FileNotFoundError as exc:
            raise DataStoreError(f"Missing JSON seed file: {path}") from exc
        except json.JSONDecodeError as exc:
            raise DataStoreError(f"Invalid JSON in seed file: {path}") from exc

    def _read_text(self, path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise DataStoreError(f"Missing policy file: {path}") from exc

    def _parse_front_matter(self, raw_markdown: str) -> tuple[dict[str, Any], str]:
        if not raw_markdown.startswith("---\n"):
            raise DataStoreError("Policy file missing YAML front matter opening delimiter")

        try:
            _, remainder = raw_markdown.split("---\n", 1)
            yaml_blob, markdown_body = remainder.split("\n---\n", 1)
        except ValueError as exc:
            raise DataStoreError("Policy file missing YAML front matter closing delimiter") from exc

        metadata = yaml.safe_load(yaml_blob)
        if not isinstance(metadata, dict):
            raise DataStoreError("Policy front matter must parse to an object")

        return metadata, markdown_body

    def _serialize_json(self, payload: Any) -> str | None:
        if payload is None:
            return None
        return json.dumps(payload, sort_keys=True)

    def _utc_now(self) -> str:
        return datetime.now(UTC).isoformat()

    def _parse_timestamp(self, timestamp: str) -> datetime:
        return datetime.fromisoformat(timestamp)
