# Admin panel — Task 6 index

Task 6 from `prompts/cursor_summary/2_project_overview_tasks.md` is **split into two plans** (G1 locked **30 Aug 2026**). Do not implement from this file — use the phase SoT below.

| Phase | Plan (source of truth) | Scope |
| --- | --- | --- |
| **6a** | [`9a_admin_panel.md`](./9a_admin_panel.md) | Users / roles / groups — Keycloak + Postgres dual-write + Admin identity UI |
| **6b** | [`9b_admin_panel.md`](./9b_admin_panel.md) | File ACL assign/revoke + `acl_sync_jobs` + OpenSearch `allowed_*` sync + Files ACL UI |

**Order:** finish **6a** proofs, then **6b**. Flip Task 6 checkboxes in `2_project_overview_tasks.md` only when **both** are done.

### Locked shared decisions (see phase files for detail)

| ID | Lock |
| --- | --- |
| G1 | Two files / two phases (this split) — **LOCKED** |
| G2 | No Celery/Redis — Postgres jobs + BackgroundTasks — **LOCKED** |
| G3–G8 | **LOCKED** (principals roles/groups only; default viewer; KC→PG identity; PG→OS ACL job; no rename; no hard user delete) |
| C1–C12 | **LOCKED** 30 Aug 2026; C2/C3 permanent password (`temporary=false`) |

### Prior combined draft

The pre-split combined plan lived in this path; content was moved into 9a/9b on **30 Aug 2026**. Prefer the phase files for implementation.

### Status

| Phase | Status |
| --- | --- |
| 6a Identity | **Done 30 Aug 2026** — see `prompts/summary/8a_admin_panel.md`; Proof 10 (React smoke) is human |
| 6b File ACL + sync | **Done 30 Aug 2026** — see `prompts/summary/8b_admin_panel.md`; Proof 10 (React smoke) is human |

### Changelog

| Date | Change |
| --- | --- |
| 30 Aug 2026 | Combined plan created, then C/G locks applied. |
| 30 Aug 2026 | **G1 locked as two files:** replaced combined body with this index; detailed plans → `9a_admin_panel.md`, `9b_admin_panel.md`. |
| 30 Aug 2026 | **6b done** — `prompts/summary/8b_admin_panel.md`; Task 6 boxes flipped. |
