from services.storage import object_store


def test_neon_s3_environment_is_supported(monkeypatch):
    for key in (
        "PGF_OBJECT_STORAGE_ENDPOINT",
        "PGF_OBJECT_STORAGE_BUCKET",
        "PGF_OBJECT_STORAGE_ACCESS_KEY",
        "PGF_OBJECT_STORAGE_SECRET_KEY",
        "PGF_OBJECT_STORAGE_REGION",
        "NEXORA_OBJECT_STORAGE_BUCKET",
    ):
        monkeypatch.delenv(key, raising=False)

    monkeypatch.setenv("AWS_ENDPOINT_URL_S3", "https://s3.example.neon.tech")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test-access")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test-secret")
    monkeypatch.setenv("AWS_REGION", "us-east-2")
    monkeypatch.setenv("PGF_OBJECT_STORAGE_BUCKET", "nexora-assets")

    assert object_store.configured()
    assert object_store.bucket() == "nexora-assets"


def test_legacy_r2_environment_remains_supported(monkeypatch):
    for key in (
        "AWS_ENDPOINT_URL_S3",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_REGION",
        "PGF_OBJECT_STORAGE_ENDPOINT",
        "PGF_OBJECT_STORAGE_BUCKET",
        "PGF_OBJECT_STORAGE_ACCESS_KEY",
        "PGF_OBJECT_STORAGE_SECRET_KEY",
    ):
        monkeypatch.delenv(key, raising=False)

    monkeypatch.setenv("PGF_OBJECT_STORAGE_ENDPOINT", "https://account.r2.cloudflarestorage.com")
    monkeypatch.setenv("PGF_OBJECT_STORAGE_BUCKET", "nexora-assets")
    monkeypatch.setenv("PGF_OBJECT_STORAGE_ACCESS_KEY", "legacy-access")
    monkeypatch.setenv("PGF_OBJECT_STORAGE_SECRET_KEY", "legacy-secret")

    assert object_store.configured()
    assert object_store.bucket() == "nexora-assets"


def test_missing_storage_credentials_fail_closed(monkeypatch):
    for key in (
        "AWS_ENDPOINT_URL_S3",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_REGION",
        "PGF_OBJECT_STORAGE_ENDPOINT",
        "PGF_OBJECT_STORAGE_BUCKET",
        "PGF_OBJECT_STORAGE_ACCESS_KEY",
        "PGF_OBJECT_STORAGE_SECRET_KEY",
        "NEXORA_OBJECT_STORAGE_BUCKET",
    ):
        monkeypatch.delenv(key, raising=False)

    assert not object_store.configured()
