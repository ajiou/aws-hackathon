"""Read-only, process-cached serving artifacts from disk or private S3."""

import json
from copy import deepcopy
from pathlib import PurePosixPath
from threading import RLock
from typing import Any

from botocore.exceptions import ClientError

from backend.config import Settings
from backend.privacy import assert_no_pii
from backend.schemas import Meta, Park


class DataNotReady(Exception):
    """A required serving artifact has not been published yet."""


def records(document: Any) -> list[dict]:
    """Accept a record array, an items envelope, or a park-id keyed mapping."""
    if isinstance(document, list):
        return document
    if not isinstance(document, dict):
        raise TypeError("Invalid serving document")
    if "park_id" in document:
        return [document]
    if "items" in document:
        if not isinstance(document["items"], list):
            raise ValueError("Invalid serving items")
        return document["items"]
    result = []
    for park_id, value in document.items():
        for row in value if isinstance(value, list) else [value]:
            if not isinstance(row, dict):
                raise TypeError("Invalid serving record")
            result.append({"park_id": park_id, **row})
    return result


class ServingStore:
    def __init__(self, settings: Settings, s3_client=None):
        self.settings = settings
        self._s3 = s3_client
        self._cache: dict[str, Any] = {}
        self._models: dict[str, Any] = {}
        self._lock = RLock()

    @property
    def s3(self):
        if self._s3 is None:
            import boto3
            from botocore.config import Config

            self._s3 = boto3.client(
                "s3",
                config=Config(
                    signature_version="s3v4",
                    connect_timeout=2,
                    read_timeout=3,
                    retries={"max_attempts": 1},
                ),
            )
        return self._s3

    @property
    def version(self) -> str:
        meta = self._models.get("meta")
        return meta.version if meta else ""

    def load(self, key: str, *, optional: bool = False):
        # All callers use internal names, never a user-controlled path.
        if not key or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for c in key):
            raise ValueError("Invalid artifact key")
        with self._lock:
            if key in self._cache:
                return self._cache[key]
            try:
                if self.settings.serving_dir is not None:
                    with (self.settings.serving_dir / f"{key}.json").open(encoding="utf-8") as f:
                        value = json.load(f)
                elif self.settings.data_bucket:
                    obj = self.s3.get_object(
                        Bucket=self.settings.data_bucket, Key=f"serving/{key}.json"
                    )
                    try:
                        value = json.loads(obj["Body"].read())
                    finally:
                        obj["Body"].close()
                else:
                    raise FileNotFoundError
            except (FileNotFoundError, ClientError) as exc:
                if isinstance(exc, ClientError) and exc.response["Error"]["Code"] not in {
                    "NoSuchKey",
                    "404",
                    "NotFound",
                }:
                    # AccessDenied is an infrastructure failure, not missing data.
                    raise
                if optional:
                    self._cache[key] = None
                    return None
                raise DataNotReady from exc
            assert_no_pii(value)
            self._cache[key] = value
            return value

    def validated(self, key: str, schema):
        with self._lock:
            if key not in self._models:
                self._models[key] = schema.model_validate(self.load(key))
            return self._models[key]

    def meta(self) -> Meta:
        return self.validated("meta", Meta)

    def parks(self) -> dict[str, Park]:
        with self._lock:
            if "parks-index" not in self._models:
                meta = self.meta()
                document = self.load("scores")
                basic = {
                    row["park_id"]: row for row in records(self.load("parks", optional=True) or {})
                }
                index = {}
                for source in records(document):
                    row = deepcopy({**basic.get(source["park_id"], {}), **source})
                    kind = row.get("institution_type", row.get("type"))
                    row.setdefault("institution_type", kind)
                    row.setdefault("type", kind)
                    row.setdefault("as_of_date", meta.generated_at[:10])
                    # Legacy mocks retain a nominal weight for missing dimensions.
                    # Normalize this known inconsistency without inventing a score.
                    for dim in row["dimensions"].values():
                        if dim["applicable"] is False and dim["score"] is None:
                            dim["weight"] = None
                    for flag in row["finance_flags"]:
                        flag.setdefault("validated", False)
                    park = Park.model_validate(row)
                    if park.park_id in index:
                        raise ValueError("Duplicate park id")
                    index[park.park_id] = park
                self._models["parks-index"] = index
                self._models["ranked-parks"] = sorted(
                    (p for p in index.values() if p.is_active),
                    key=lambda p: (p.risk.rank, p.park_id),
                )
            return self._models["parks-index"]

    def ranked(self) -> list[Park]:
        self.parks()
        return self._models["ranked-parks"]

    def related(self, key: str, park_id: str) -> list[dict]:
        cache_key = f"related-{key}"
        with self._lock:
            if cache_key not in self._models:
                index: dict[str, list] = {}
                for row in records(self.load(key, optional=True) or {}):
                    index.setdefault(row["park_id"], []).append(row)
                self._models[cache_key] = index
            return deepcopy(self._models[cache_key].get(park_id, []))

    def finance(self, park_id: str, embedded: list[dict]) -> list[dict]:
        rows = self.related("finance", park_id) or deepcopy(embedded)
        for row in rows:
            if row.get("validated") is not False:
                raise ValueError("Finance must be marked unvalidated")
            key = row.get("source_pdf")
            row.pop("pdf_url", None)  # Never reuse expiring URLs from an artifact.
            if key:
                path = PurePosixPath(key)
                if not key.startswith("raw/pdf/") or ".." in path.parts or "\\" in key:
                    raise ValueError("PDF is outside the permitted prefix")
                row["pdf_url"] = (
                    self.s3.generate_presigned_url(
                        "get_object",
                        Params={"Bucket": self.settings.data_bucket, "Key": key},
                        ExpiresIn=900,
                    )
                    if self.settings.data_bucket
                    else None
                )
        return rows
