# Search, View, and Open

Shipped Task 5. Source: `prompts/summary/7_search_view_api.md`. `prompts/summary/6_search_view.md` is the search half only.

```
POST /search  → user JWT → parallel match + neural → min_max + [0.3, 0.7] → hits without embedding
GET /files    → Postgres files ⋈ file_acl ⋈ roles/groups (JWT names; editor ⇒ viewer; ignore _empty)
GET /files/{id}/content → ACL, then MinIO stream of files.object_store_path
```

Search hits stay at chunk grain. They are not collapsed to one row per file.

List and Open:

- `require_product_user`. Realm `admin` does not bypass `file_acl`.
- Match JWT role and group names. `permission` is `viewer` or `editor`.
- Missing file → 404. ACL deny → 403. No token → 401.
- `display_name` is the basename of `object_store_path` (no filename column).
- Content-Type: pdf, txt, csv, else octet-stream. `Content-Disposition: attachment`. No HTTP Range. No in-browser PDF preview.
- The UI downloads via an authenticated fetch to a blob. A plain `<a href>` would drop the Bearer token.
- Synthetic `proof-*` hits have no MinIO object; Open shows an error.

Optional seed (not the product path): `uv run python -m scripts.seed_file_acl_for_proofs` grants up to two recent files (`search-user` viewer, and `engineering` viewer) and `update_by_query` as basic admin. Product search still uses the user JWT.
