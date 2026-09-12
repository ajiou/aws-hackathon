"""Reject unredacted person fields before serving data.

This is a defense against accidental raw-data ingestion, not a name recognizer.
Serving artifacts must already be de-identified by the ETL pipeline.
"""

import re

PERSON_FIELDS = {
    "owner",
    "owner_name",
    "person_name",
    "actor",
    "actor_name",
    "principal",
    "principal_name",
    "responsible_person",
    "負責人",
    "負責人姓名",
    "行為人",
    "姓名",
}
PERSON_LABEL = re.compile(r"(?:負責人|行為人|園長|姓名)\s*[:：]\s*[^\s，,。；;]{2,}")
HASH = re.compile(r"[0-9a-f]{12}|[0-9a-f]{64}")


def assert_no_pii(value: object) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key.casefold() in PERSON_FIELDS:
                raise ValueError("Personal-data field in serving artifact")
            if (
                key == "owner_key"
                and child is not None
                and (not isinstance(child, str) or not HASH.fullmatch(child))
            ):
                raise ValueError("Invalid owner hash")
            assert_no_pii(child)
    elif isinstance(value, list):
        for child in value:
            assert_no_pii(child)
    elif isinstance(value, str) and PERSON_LABEL.search(value):
        raise ValueError("Unredacted person label in serving artifact")
