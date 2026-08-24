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
    db_required: bool = False

    @classmethod
    def from_env(cls) -> "StoreConfig":
        return cls(
            db_host=os.environ.get("DB_HOST"),
            db_port=int(os.environ.get("DB_PORT", "5432")),
            db_name=os.environ.get("SOSOG_DB_NAME"),
            db_user=os.environ.get("DB_USER"),
            db_password=os.environ.get("DB_PASSWORD"),
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

    def _write(self, sql: str, parameters: tuple[Any, ...]) -> bool:
        connection = self._connect()
        if connection is None:
            return False
        try:
            with connection:
                with connection.cursor() as cursor:
                    cursor.execute(sql, parameters)
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

    def list_classification_history(self, task_type_id: str) -> list[dict[str, Any]]:
        return self._read_all(
            """SELECT * FROM sosog_v1.classifications WHERE task_type_id = %s
               ORDER BY created_at ASC, classification_id ASC""",
            (task_type_id,),
        )

    @staticmethod
    def _require(value: Mapping[str, Any], required: set[str], label: str) -> None:
        missing = sorted(required - value.keys())
        if missing:
            raise ValueError(f"{label} row missing fields: {missing}")
