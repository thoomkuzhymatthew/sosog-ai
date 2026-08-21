"""S3-first persistence with optional PostgreSQL indexing.

Each row is written to an immutable local spool and S3 object before the
best-effort database upsert. A database outage therefore never loses the
benchmark trace and can be repaired by replaying the spool.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class StoreConfig:
    bucket: str
    prefix: str = "vertical-expansion"
    spool_dir: Path = Path("/opt/sosog/checkpoints")
    db_host: str | None = None
    db_port: int = 5432
    db_name: str | None = None
    db_user: str | None = None
    db_password: str | None = None
    db_required: bool = False

    @classmethod
    def from_env(cls) -> "StoreConfig":
        bucket = os.environ.get("SOSOG_ARTIFACT_BUCKET")
        if not bucket:
            raise ValueError("SOSOG_ARTIFACT_BUCKET is required")
        return cls(
            bucket=bucket,
            prefix=os.environ.get("SOSOG_ARTIFACT_PREFIX", "vertical-expansion"),
            spool_dir=Path(
                os.environ.get("SOSOG_SPOOL_DIR", "/opt/sosog/checkpoints")
            ),
            db_host=os.environ.get("DB_HOST"),
            db_port=int(os.environ.get("DB_PORT", "5432")),
            db_name=os.environ.get("DB_NAME"),
            db_user=os.environ.get("DB_USER"),
            db_password=os.environ.get("DB_PASSWORD"),
            db_required=os.environ.get("SOSOG_DB_REQUIRED") == "1",
        )

    @property
    def database_configured(self) -> bool:
        return all((self.db_host, self.db_name, self.db_user, self.db_password))


class ResearchStore:
    def __init__(self, config: StoreConfig):
        self.config = config
        self.last_db_error: str | None = None
        self._database_disabled = False

    @staticmethod
    def _render(value: dict[str, Any]) -> bytes:
        return (json.dumps(value, sort_keys=True, default=str) + "\n").encode()

    @staticmethod
    def _safe_segment(value: Any) -> str:
        text = str(value)
        if not text or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for char in text):
            raise ValueError(f"unsafe artifact path segment: {text!r}")
        return text

    def _put_immutable(self, key: str, body: bytes) -> str:
        import boto3

        boto3.client("s3").put_object(
            Bucket=self.config.bucket,
            Key=key,
            Body=body,
            ContentType="application/json",
            ServerSideEncryption="AES256",
        )
        return f"s3://{self.config.bucket}/{key}"

    def _connect(self):
        if not self.config.database_configured or self._database_disabled:
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
            self.last_db_error = f"{type(exc).__name__}: {exc}"
            self._database_disabled = True
            if self.config.db_required:
                raise
            return None

    def record_run(self, value: dict[str, Any]) -> None:
        required = {"run_id", "milestone", "vertical", "status", "subject_model", "harness_name", "harness_commit"}
        missing = sorted(required - set(value))
        if missing:
            raise ValueError(f"run row missing fields: {missing}")
        body = self._render(value)
        run_id = self._safe_segment(value["run_id"])
        key = f"{self.config.prefix}/{run_id}/manifests/run.json"
        self._put_immutable(key, body)
        connection = self._connect()
        if connection is None:
            return
        with connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO sosog_research.runs
                    (run_id, milestone, vertical, status, subject_model,
                     harness_name, harness_commit, config, cost_usd, started_at,
                     completed_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, now())
                ON CONFLICT (run_id) DO UPDATE SET
                    status = excluded.status,
                    cost_usd = excluded.cost_usd,
                    completed_at = excluded.completed_at,
                    config = excluded.config,
                    updated_at = now()
                """,
                (
                    value["run_id"], value["milestone"], value["vertical"],
                    value["status"], value["subject_model"], value["harness_name"],
                    value["harness_commit"], json.dumps(value.get("config", {})),
                    value.get("cost_usd", 0), value.get("started_at"),
                    value.get("completed_at"),
                ),
            )

    def record_task_run(self, value: dict[str, Any]) -> dict[str, str]:
        required = {
            "run_id", "task_id", "trial", "seed", "status",
            "requested_model_route",
        }
        missing = sorted(required - set(value))
        if missing:
            raise ValueError(f"task run row missing fields: {missing}")
        run_id = self._safe_segment(value["run_id"])
        task_id = self._safe_segment(value["task_id"])
        trial = int(value["trial"])
        seed = int(value["seed"])
        body = self._render(value)
        digest = hashlib.sha256(body).hexdigest()
        local_path = (
            self.config.spool_dir / run_id / "rows" / task_id / f"{trial}-{seed}.json"
        )
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_bytes(body)
        key = f"{self.config.prefix}/{run_id}/rows/{task_id}/{trial}-{seed}-{digest}.json"
        uri = self._put_immutable(key, body)

        connection = self._connect()
        if connection is not None:
            with connection, connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO sosog_research.task_runs
                        (run_id, task_id, trial, seed, status, passed, reward,
                         requested_model_route, actual_model_route, fallback_depth,
                         usage, cost_usd, trace_s3_uri, trace_sha256, error,
                         metadata, started_at, completed_at, updated_at)
                    VALUES
                        (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                         %s::jsonb, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, now())
                    ON CONFLICT (run_id, task_id, trial, seed) DO UPDATE SET
                        status = excluded.status,
                        passed = excluded.passed,
                        reward = excluded.reward,
                        actual_model_route = excluded.actual_model_route,
                        fallback_depth = excluded.fallback_depth,
                        usage = excluded.usage,
                        cost_usd = excluded.cost_usd,
                        trace_s3_uri = excluded.trace_s3_uri,
                        trace_sha256 = excluded.trace_sha256,
                        error = excluded.error,
                        metadata = excluded.metadata,
                        completed_at = excluded.completed_at,
                        updated_at = now()
                    """,
                    (
                        value["run_id"], task_id, trial, seed, value["status"],
                        value.get("passed"), value.get("reward"),
                        value["requested_model_route"], value.get("actual_model_route"),
                        value.get("fallback_depth", 0), json.dumps(value.get("usage", {})),
                        value.get("cost_usd", 0), uri, digest,
                        json.dumps(value.get("error")), json.dumps(value.get("metadata", {})),
                        value.get("started_at"), value.get("completed_at"),
                    ),
                )
        return {"s3_uri": uri, "sha256": digest, "local_path": str(local_path)}
