"""Object storage behind one small interface: S3 in prod, a local folder in dev and tests.

Both backends use the same keys, so the layout below is the contract:

    raw/{source}/{company}/load_date=YYYY-MM-DD/{content_sha256[:16]}.json
    state/{source}/{company}.json          # last landed hash, used to skip unchanged boards
    ops/pipeline_runs/run_date=YYYY-MM-DD/run_id={run_id}.jsonl
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol

import boto3
from botocore.exceptions import ClientError


class Storage(Protocol):
    def exists(self, key: str) -> bool: ...
    def put_bytes(
        self, key: str, body: bytes, content_type: str, metadata: dict[str, str] | None = None
    ) -> None: ...
    def get_bytes(self, key: str) -> bytes | None: ...
    def uri(self, key: str) -> str: ...


def put_json(store: Storage, key: str, obj: Any) -> None:
    body = json.dumps(obj, sort_keys=True, indent=2).encode()
    store.put_bytes(key, body, "application/json")


def get_json(store: Storage, key: str) -> Any | None:
    raw = store.get_bytes(key)
    return None if raw is None else json.loads(raw)


class LocalStorage:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def _path(self, key: str) -> Path:
        return self.root / key

    def exists(self, key: str) -> bool:
        return self._path(key).exists()

    def put_bytes(
        self, key: str, body: bytes, content_type: str, metadata: dict[str, str] | None = None
    ) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(body)
        tmp.replace(path)  # atomic on one filesystem, so readers never see half a file

    def get_bytes(self, key: str) -> bytes | None:
        path = self._path(key)
        return path.read_bytes() if path.exists() else None

    def uri(self, key: str) -> str:
        return str(self._path(key))


class S3Storage:
    def __init__(
        self, bucket: str, prefix: str = "", region: str | None = None, client: Any | None = None
    ) -> None:
        self.bucket = bucket
        self.prefix = prefix.strip("/")
        self.client = client or boto3.client("s3", region_name=region)

    def _key(self, key: str) -> str:
        return f"{self.prefix}/{key}" if self.prefix else key

    def exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=self._key(key))
            return True
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in {"404", "NoSuchKey", "NotFound"}:
                return False
            raise

    def put_bytes(
        self, key: str, body: bytes, content_type: str, metadata: dict[str, str] | None = None
    ) -> None:
        self.client.put_object(
            Bucket=self.bucket,
            Key=self._key(key),
            Body=body,
            ContentType=content_type,
            Metadata=metadata or {},
            ServerSideEncryption="AES256",
        )

    def get_bytes(self, key: str) -> bytes | None:
        try:
            obj = self.client.get_object(Bucket=self.bucket, Key=self._key(key))
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in {"404", "NoSuchKey", "NotFound"}:
                return None
            raise
        return obj["Body"].read()

    def uri(self, key: str) -> str:
        return f"s3://{self.bucket}/{self._key(key)}"
