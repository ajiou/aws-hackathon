import io
import json
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import Mock

import boto3
import pytest
from botocore.stub import Stubber
from fastapi.testclient import TestClient
from mangum import Mangum

from backend.app import create_app
from backend.config import Settings
from backend.store import ServingStore


@pytest.fixture
def s3():
    # Dummy credentials explicitly prevent metadata/network credential lookup.
    return boto3.client(
        "s3", region_name="us-west-2", aws_access_key_id="testing", aws_secret_access_key="testing"
    )


def test_s3_reads_once_and_closes_body(s3, artifacts):
    store = ServingStore(Settings(data_bucket="private-bucket"), s3)
    body = io.BytesIO(json.dumps(artifacts["meta"]).encode())
    with Stubber(s3) as stub:
        stub.add_response(
            "get_object", {"Body": body}, {"Bucket": "private-bucket", "Key": "serving/meta.json"}
        )
        with ThreadPoolExecutor(max_workers=8) as pool:
            versions = list(pool.map(lambda _: store.meta().version, range(20)))
        assert versions == ["test-v1"] * 20
        assert body.closed
        stub.assert_no_pending_responses()


@pytest.mark.parametrize("code,status", [("NoSuchKey", 503), ("AccessDenied", 500)])
def test_s3_errors_are_sanitized(s3, code, status):
    settings = Settings(data_bucket="secret-bucket")
    store = ServingStore(settings, s3)
    with Stubber(s3) as stub:
        stub.add_client_error(
            "get_object", service_error_code=code, service_message="secret-bucket credential detail"
        )
        with TestClient(create_app(settings, store)) as client:
            response = client.get("/api/v1/meta")
            assert response.status_code == status
            assert "secret-bucket" not in response.text and "credential" not in response.text


def test_pdf_signing_is_scoped_expires_and_not_cached(serving_dir):
    document = {
        "items": [{"park_id": "park-1", "validated": False, "source_pdf": "raw/pdf/park-1/113.pdf"}]
    }
    (serving_dir / "finance.json").write_text(json.dumps(document))
    s3 = Mock()
    s3.generate_presigned_url.side_effect = [
        "https://signed.example/one",
        "https://signed.example/two",
    ]
    settings = Settings(serving_dir=serving_dir, data_bucket="private-bucket")
    with TestClient(create_app(settings, ServingStore(settings, s3))) as client:
        first = client.get("/api/v1/parks/park-1")
        second = client.get("/api/v1/parks/park-1")
        assert first.json()["finance"][0]["pdf_url"] != second.json()["finance"][0]["pdf_url"]
        assert first.headers["cache-control"] == "no-store"
        s3.generate_presigned_url.assert_called_with(
            "get_object",
            Params={"Bucket": "private-bucket", "Key": "raw/pdf/park-1/113.pdf"},
            ExpiresIn=900,
        )


@pytest.mark.parametrize(
    "key", ["raw/private.pdf", "raw/pdf/../private.pdf", "https://example/a.pdf"]
)
def test_pdf_rejects_keys_outside_permitted_prefix(serving_dir, key):
    (serving_dir / "finance.json").write_text(
        json.dumps(
            [
                {"park_id": "park-1", "validated": False, "source_pdf": key},
            ]
        )
    )
    settings = Settings(serving_dir=serving_dir, data_bucket="private-bucket")
    s3 = Mock()
    with TestClient(create_app(settings, ServingStore(settings, s3))) as client:
        assert client.get("/api/v1/parks/park-1").status_code == 500
        s3.generate_presigned_url.assert_not_called()


def test_lambda_http_api_repeated_queries_and_logs(serving_dir, caplog):
    caplog.set_level("INFO", logger="watchdog.api")
    app = create_app(Settings(serving_dir=serving_dir))
    handler = Mangum(app, lifespan="off")
    event = {
        "version": "2.0",
        "routeKey": "$default",
        "rawPath": "/api/v1/parks",
        "rawQueryString": "type=%E5%85%AC%E7%AB%8B&type=%E7%A7%81%E7%AB%8B",
        "headers": {"host": "example.execute-api.us-west-2.amazonaws.com"},
        "requestContext": {
            "domainName": "example.execute-api.us-west-2.amazonaws.com",
            "stage": "$default",
            "requestId": "gateway-id",
            "http": {
                "method": "GET",
                "path": "/api/v1/parks",
                "sourceIp": "127.0.0.1",
                "protocol": "HTTP/1.1",
            },
        },
        "isBase64Encoded": False,
    }
    context = SimpleNamespace(aws_request_id="lambda-request-id")
    first = handler(event, context)
    second = handler(event, context)
    assert first["statusCode"] == 200
    assert json.loads(first["body"])["total"] == 2
    assert first["headers"]["x-request-id"] != second["headers"]["x-request-id"]
    assert "lambda-request-id" in caplog.text
    assert first["headers"]["x-request-id"] in caplog.text


def test_environment_precedence(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_BUCKET", "bucket")
    monkeypatch.delenv("SERVING_DIR", raising=False)
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    settings = Settings.from_env()
    assert settings.serving_dir is None and settings.cors_origins == ()
    monkeypatch.setenv("SERVING_DIR", str(tmp_path))
    monkeypatch.setenv("CORS_ORIGINS", "https://example.cloudfront.net")
    settings = Settings.from_env()
    assert settings.serving_dir == tmp_path
    assert settings.cors_origins == ("https://example.cloudfront.net",)
