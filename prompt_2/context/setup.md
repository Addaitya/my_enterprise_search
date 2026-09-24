# Local setup

Shipped. Source: `prompts/summary/9_setup.md`. Humans follow the root `README.md`.

Entry point is `./setup/setup.sh`. All setup code lives under `setup/`. The script calls Alembic and `init_services`; it does not fork Keycloak, OpenSearch, or MinIO configure logic.

Order: copy env once (`--force-env` overwrites), Compose, wait for postgres, keycloak, opensearch, and minio, migrate, init, verify model id + index + bucket, `bun install`, print a summary. Re-runs are safe. `--with-seed` is opt-in and exits 0 with a message when there are no files to seed. There is no `--destroy-volumes`. `vm.max_map_count` problems print instructions only.

Fresh clone: Alembic `upgrade head` before the identity mirror. The mirror does not create tables.
