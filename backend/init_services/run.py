from __future__ import annotations

from app.core.config import get_settings
from init_services import identity_sync, keycloak, minio_bucket, opensearch
from init_services.wait import http_ok, wait_for


def main() -> None:
    settings = get_settings()
    print(f"bootstrapping services for {settings.app_name}")

    postgres_ready = wait_for(
        "postgres",
        lambda: _postgres_ready(),
        timeout_s=8,
        interval_s=2,
    )
    keycloak_ready = wait_for(
        "keycloak",
        http_ok(f"{settings.keycloak_url}/realms/{settings.keycloak_realm}"),
        timeout_s=8,
        interval_s=2,
    )
    opensearch_ready = wait_for(
        "opensearch",
        http_ok(
            f"{settings.opensearch_url}/_cluster/health",
            verify=settings.opensearch_verify_certs,
            auth=("admin", settings.opensearch_initial_admin_password),
        ),
        timeout_s=8,
        interval_s=2,
    )
    minio_ready = wait_for(
        "minio",
        http_ok(f"http://{settings.minio_endpoint}/minio/health/live"),
        timeout_s=8,
        interval_s=2,
    )

    if keycloak_ready:
        keycloak.configure()
    if postgres_ready and keycloak_ready:
        identity_sync.sync()
    elif not postgres_ready:
        print("[skip] identity mirror; postgres is down")
    else:
        print("[skip] identity mirror; keycloak is down")
    if opensearch_ready:
        opensearch.configure()
    if minio_ready:
        minio_bucket.configure()

    print("init_services finished (missing services were skipped)")


def _postgres_ready() -> bool:
    from sqlalchemy import create_engine, text

    settings = get_settings()
    engine = create_engine(settings.database_url, pool_pre_ping=True)
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    engine.dispose()
    return True


if __name__ == "__main__":
    main()
