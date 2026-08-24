"""Read/write access to the SOSOG V1 PostgreSQL database."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Callable, Mapping


ConnectionFactory = Callable[[], Any]


@dataclass(frozen=True)
class StoreConfig:
    """Connection settings for the product database."""

    db_host: str | None = None
    db_port: int = 5432
    db_name: str | None = None
    db_user: str | None = None
    db_password: str | None = None
    db_sslmode: str = "require"
    db_required: bool = False

    @classmethod
    def from_env(cls) -> "StoreConfig":
        return cls(
            db_host=os.environ.get("DB_HOST"),
            db_port=int(os.environ.get("DB_PORT", "5432")),
            db_name=os.environ.get("SOSOG_DB_NAME"),
            db_user=os.environ.get("DB_USER"),
            db_password=os.environ.get("DB_PASSWORD"),
            db_sslmode=os.environ.get("SOSOG_DB_SSLMODE", "require"),
            db_required=os.environ.get("SOSOG_DB_REQUIRED") == "1",
        )

    @property
    def database_configured(self) -> bool:
        return all((self.db_host, self.db_name, self.db_user, self.db_password))


class SosogStore:
    """Best-effort store with injectable connections for isolated tests.

    A failed operation returns ``False`` for writes, ``None`` for singular
    reads, and an empty list for list reads. Set ``SOSOG_DB_REQUIRED=1`` (or
    ``StoreConfig.db_required``) to raise database errors instead.
    """

    def __init__(
        self,
        config: StoreConfig | None = None,
        *,
        connection_factory: ConnectionFactory | None = None,
    ) -> None:
        self.config = config or StoreConfig.from_env()
        self._connection_factory = connection_factory
        self.last_db_error: str | None = None
        self._database_disabled = False

    def _connect(self) -> Any | None:
        if self._database_disabled:
            return None
        if self._connection_factory is not None:
            try:
                return self._connection_factory()
            except Exception as exc:
                return self._handle_error(exc)
        if not self.config.database_configured:
            return None
        try:
            import psycopg

            return psycopg.connect(
                host=self.config.db_host,
                port=self.config.db_port,
                dbname=self.config.db_name,
                user=self.config.db_user,
                password=self.config.db_password,
                sslmode=self.config.db_sslmode,
                connect_timeout=5,
            )
        except Exception as exc:
            return self._handle_error(exc)

    def _handle_error(self, exc: Exception) -> None:
        self.last_db_error = f"{type(exc).__name__}: {exc}"
        self._database_disabled = True
        if self.config.db_required:
            raise exc
        return None

    @staticmethod
    def _json(value: Any, default: Any) -> str:
        return json.dumps(default if value is None else value, default=str)

    @staticmethod
    def _row(cursor: Any, row: Any) -> dict[str, Any] | None:
        if row is None:
            return None
        if isinstance(row, Mapping):
            return dict(row)
        names = [column.name if hasattr(column, "name") else column[0] for column in cursor.description]
        return dict(zip(names, row))

    def _write(
        self, sql: str, parameters: tuple[Any, ...], *, require_affected: bool = False
    ) -> bool:
        connection = self._connect()
        if connection is None:
            return False
        try:
            with connection:
                with connection.cursor() as cursor:
                    cursor.execute(sql, parameters)
                    if require_affected and getattr(cursor, "rowcount", 1) == 0:
                        return False
            return True
        except Exception as exc:
            self._handle_error(exc)
            return False

    def _read_one(self, sql: str, parameters: tuple[Any, ...]) -> dict[str, Any] | None:
        connection = self._connect()
        if connection is None:
            return None
        try:
            with connection:
                with connection.cursor() as cursor:
                    cursor.execute(sql, parameters)
                    return self._row(cursor, cursor.fetchone())
        except Exception as exc:
            self._handle_error(exc)
            return None

    def _read_all(self, sql: str, parameters: tuple[Any, ...]) -> list[dict[str, Any]]:
        connection = self._connect()
        if connection is None:
            return []
        try:
            with connection:
                with connection.cursor() as cursor:
                    cursor.execute(sql, parameters)
                    return [self._row(cursor, row) for row in cursor.fetchall()]  # type: ignore[misc]
        except Exception as exc:
            self._handle_error(exc)
            return []

    def record_episode(self, value: Mapping[str, Any]) -> bool:
        required = {"episode_id", "source_trace_id", "outcome_status"}
        self._require(value, required, "episode")
        return self._write(
            """INSERT INTO sosog_v1.episodes
               (episode_id, engagement_id, task_type_id, source_trace_id,
                outcome_status, outcome_success, outcome_success_source,
                outcome_confidence, calls, cost_usd, started_at, completed_at,
                raw_artifact_uri, raw_artifact_sha256, metadata)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s,
                       %s, %s, %s, %s::jsonb)""",
            (
                value["episode_id"], value.get("engagement_id", "default"),
                value.get("task_type_id"), value["source_trace_id"],
                value["outcome_status"], value.get("outcome_success"),
                value.get("outcome_success_source", "unknown"),
                value.get("outcome_confidence"), self._json(value.get("calls"), []),
                value.get("cost_usd", 0), value.get("started_at"),
                value.get("completed_at"), value.get("raw_artifact_uri"),
                value.get("raw_artifact_sha256"), self._json(value.get("metadata"), {}),
            ),
        )

    def get_episode(self, episode_id: str) -> dict[str, Any] | None:
        return self._read_one(
            "SELECT * FROM sosog_v1.episodes WHERE episode_id = %s", (episode_id,)
        )

    def list_episodes_for_task_type(self, task_type_id: str) -> list[dict[str, Any]]:
        return self._read_all(
            """SELECT * FROM sosog_v1.episodes WHERE task_type_id = %s
               ORDER BY created_at ASC, episode_id ASC""",
            (task_type_id,),
        )

    def assign_episode_task_type(self, episode_id: str, task_type_id: str) -> bool:
        """Link an ingested episode after automated task discovery."""
        if not episode_id or not task_type_id:
            raise ValueError("episode_id and task_type_id must be non-empty")
        return self._write(
            "UPDATE sosog_v1.episodes SET task_type_id = %s WHERE episode_id = %s",
            (task_type_id, episode_id),
        )

    def update_episode_outcome(
        self,
        episode_id: str,
        *,
        success: bool | None,
        success_source: str,
        confidence: float | None,
        rationale: str | None = None,
    ) -> bool:
        """Persist an outcome judgment without replacing stronger evidence in SQL."""
        if not episode_id or not success_source:
            raise ValueError("episode_id and success_source must be non-empty")
        return self._write(
            """UPDATE sosog_v1.episodes
               SET outcome_success = %s,
                   outcome_success_source = %s,
                   outcome_confidence = %s,
                   metadata = metadata || %s::jsonb
               WHERE episode_id = %s
                 AND outcome_success_source = 'unknown'""",
            (
                success,
                success_source,
                confidence,
                self._json(
                    {"outcome_judge_rationale": rationale} if rationale else {}, {}
                ),
                episode_id,
            ),
        )

    def record_task_type(self, value: Mapping[str, Any]) -> bool:
        self._require(value, {"task_type_id", "name", "description", "source"}, "task type")
        return self._write(
            """INSERT INTO sosog_v1.task_types
               (task_type_id, engagement_id, name, description, source,
                representative_episode_ids)
               VALUES (%s, %s, %s, %s, %s, %s::jsonb)""",
            (
                value["task_type_id"], value.get("engagement_id", "default"),
                value["name"], value["description"], value["source"],
                self._json(value.get("representative_episode_ids"), []),
            ),
        )

    def get_task_type(self, task_type_id: str) -> dict[str, Any] | None:
        return self._read_one(
            "SELECT * FROM sosog_v1.task_types WHERE task_type_id = %s", (task_type_id,)
        )

    def list_task_types(self) -> list[dict[str, Any]]:
        return self._read_all(
            "SELECT * FROM sosog_v1.task_types ORDER BY created_at ASC, task_type_id ASC",
            (),
        )

    def record_classification(self, value: Mapping[str, Any]) -> bool:
        self._require(
            value,
            {"classification_id", "task_type_id", "classifier_version", "internal_action", "product_category", "confidence"},
            "classification",
        )
        return self._write(
            """INSERT INTO sosog_v1.classifications
               (classification_id, engagement_id, task_type_id,
                classifier_version, features, internal_action, product_category,
                evidence, confidence)
               VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s, %s::jsonb, %s)""",
            (
                value["classification_id"], value.get("engagement_id", "default"),
                value["task_type_id"], value["classifier_version"],
                self._json(value.get("features"), {}), value["internal_action"],
                value["product_category"], self._json(value.get("evidence"), {}),
                value["confidence"],
            ),
        )

    def get_latest_classification(self, task_type_id: str) -> dict[str, Any] | None:
        return self._read_one(
            """SELECT * FROM sosog_v1.classifications WHERE task_type_id = %s
               ORDER BY created_at DESC, classification_id DESC LIMIT 1""",
            (task_type_id,),
        )

    def get_classification(self, classification_id: str) -> dict[str, Any] | None:
        return self._read_one(
            "SELECT * FROM sosog_v1.classifications WHERE classification_id = %s",
            (classification_id,),
        )

    def list_classification_history(self, task_type_id: str) -> list[dict[str, Any]]:
        return self._read_all(
            """SELECT * FROM sosog_v1.classifications WHERE task_type_id = %s
               ORDER BY created_at ASC, classification_id ASC""",
            (task_type_id,),
        )

    def record_artifact(self, value: Mapping[str, Any]) -> bool:
        self._require(value, {"artifact_id", "kind", "uri", "sha256"}, "artifact")
        return self._write(
            """INSERT INTO sosog_v1.artifacts
               (artifact_id, engagement_id, kind, uri, sha256, size_bytes, metadata)
               VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)""",
            (value["artifact_id"], value.get("engagement_id", "default"),
             value["kind"], value["uri"], value["sha256"], value.get("size_bytes"),
             self._json(value.get("metadata"), {})),
        )

    def get_artifact(self, artifact_id: str) -> dict[str, Any] | None:
        return self._read_one(
            "SELECT * FROM sosog_v1.artifacts WHERE artifact_id = %s", (artifact_id,)
        )

    def list_artifacts(self, engagement_id: str = "default") -> list[dict[str, Any]]:
        return self._read_all(
            """SELECT * FROM sosog_v1.artifacts WHERE engagement_id = %s
               ORDER BY created_at ASC, artifact_id ASC""", (engagement_id,)
        )

    def record_proposal(self, value: Mapping[str, Any]) -> bool:
        self._require(
            value, {"proposal_id", "task_type_id", "version", "status", "artifact_id"},
            "proposal",
        )
        return self._write(
            """INSERT INTO sosog_v1.proposals
               (proposal_id, engagement_id, task_type_id, classification_id,
                version, status, artifact_id, metadata, evidence)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb)""",
            (value["proposal_id"], value.get("engagement_id", "default"),
             value["task_type_id"], value.get("classification_id"), value["version"],
             value["status"], value["artifact_id"], self._json(value.get("metadata"), {}),
             self._json(value.get("evidence"), {})),
        )

    def get_proposal(self, proposal_id: str) -> dict[str, Any] | None:
        return self._read_one(
            "SELECT * FROM sosog_v1.proposals WHERE proposal_id = %s", (proposal_id,)
        )

    def list_proposals(self, task_type_id: str) -> list[dict[str, Any]]:
        return self._read_all(
            """SELECT * FROM sosog_v1.proposals WHERE task_type_id = %s
               ORDER BY created_at ASC, proposal_id ASC""", (task_type_id,)
        )

    def record_repair_run(self, value: Mapping[str, Any]) -> bool:
        self._require(
            value, {"repair_run_id", "proposal_id", "attempt_number", "status"},
            "repair run",
        )
        return self._write(
            """INSERT INTO sosog_v1.repair_runs
               (repair_run_id, engagement_id, proposal_id, attempt_number, status,
                stop_reason, candidate_fingerprint, feedback_fingerprint, score,
                evidence, cost_usd, started_at, completed_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb,
                       %s, %s, %s)""",
            (value["repair_run_id"], value.get("engagement_id", "default"),
             value["proposal_id"], value["attempt_number"], value["status"],
             value.get("stop_reason"), value.get("candidate_fingerprint"),
             value.get("feedback_fingerprint"), self._json(value.get("score"), {}),
             self._json(value.get("evidence"), {}), value.get("cost_usd", 0),
             value.get("started_at"), value.get("completed_at")),
        )

    def list_repair_runs(self, proposal_id: str) -> list[dict[str, Any]]:
        return self._read_all(
            """SELECT * FROM sosog_v1.repair_runs WHERE proposal_id = %s
               ORDER BY attempt_number ASC, created_at ASC, repair_run_id ASC""",
            (proposal_id,),
        )

    def record_budget_event(self, value: Mapping[str, Any]) -> bool:
        self._require(value, {"budget_event_id", "event_kind", "amount_usd"}, "budget event")
        return self._write(
            """INSERT INTO sosog_v1.budget_events
               (budget_event_id, engagement_id, job_id, episode_id, repair_run_id,
                event_kind, amount_usd, input_tokens, output_tokens, model, metadata)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)""",
            (value["budget_event_id"], value.get("engagement_id", "default"),
             value.get("job_id"), value.get("episode_id"), value.get("repair_run_id"),
             value["event_kind"], value["amount_usd"], value.get("input_tokens"),
             value.get("output_tokens"), value.get("model"),
             self._json(value.get("metadata"), {})),
        )

    def list_budget_events(self, engagement_id: str = "default") -> list[dict[str, Any]]:
        return self._read_all(
            """SELECT * FROM sosog_v1.budget_events WHERE engagement_id = %s
               ORDER BY created_at ASC, budget_event_id ASC""", (engagement_id,)
        )

    def create_review_item(self, value: Mapping[str, Any]) -> bool:
        self._require(
            value, {"review_item_id", "review_type", "subject_type", "subject_id", "context"},
            "review item",
        )
        return self._write(
            """INSERT INTO sosog_v1.review_items
               (review_item_id, engagement_id, review_type, subject_type, subject_id,
                status, context)
               VALUES (%s, %s, %s, %s, %s, 'PENDING', %s::jsonb)""",
            (value["review_item_id"], value.get("engagement_id", "default"),
             value["review_type"], value["subject_type"], value["subject_id"],
             self._json(value["context"], {})),
        )

    def get_review_item(self, review_item_id: str) -> dict[str, Any] | None:
        return self._read_one(
            "SELECT * FROM sosog_v1.review_items WHERE review_item_id = %s",
            (review_item_id,),
        )

    def list_review_items(
        self, *, engagement_id: str = "default", status: str = "PENDING"
    ) -> list[dict[str, Any]]:
        return self._read_all(
            """SELECT * FROM sosog_v1.review_items
               WHERE engagement_id = %s AND status = %s
               ORDER BY created_at ASC, review_item_id ASC""",
            (engagement_id, status),
        )

    def decide_review_item(
        self, review_item_id: str, *, status: str, decision: Mapping[str, Any], reviewer: str
    ) -> bool:
        if status not in {"APPROVED", "REJECTED"}:
            raise ValueError("review status must be APPROVED or REJECTED")
        if not review_item_id or not reviewer:
            raise ValueError("review_item_id and reviewer must be non-empty")
        return self._write(
            """UPDATE sosog_v1.review_items
               SET status = %s, decision = %s::jsonb, reviewer = %s, decided_at = now()
               WHERE review_item_id = %s AND status = 'PENDING'""",
            (status, self._json(decision, {}), reviewer, review_item_id),
            require_affected=True,
        )

    @staticmethod
    def _require(value: Mapping[str, Any], required: set[str], label: str) -> None:
        missing = sorted(required - value.keys())
        if missing:
            raise ValueError(f"{label} row missing fields: {missing}")
