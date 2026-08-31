# ACL UI redesign — index

UX follow-on after Admin **6a** (`9a_admin_panel.md`) + **6b** (`9b_admin_panel.md`). Do **not** implement from this index — use the phase files below.

| Phase | Plan (source of truth) | Scope in one line |
| --- | --- | --- |
| **12a** | [`12a_file_access_ui.md`](./12a_file_access_ui.md) | **File Access UI** — Access tab, single-file manage drawer, multi-file grant/revoke to roles/groups, sync job tray |
| **12b** | [`12b_member_assignment_ui.md`](./12b_member_assignment_ui.md) | **Member Assignment UI** — multi-user → role/group, Role/Group Members tabs, Users bulk “Add to…” |

**Order:** finish **12a** (proofs + React smoke) before starting **12b**.

**Why split:** 12a mutates `file_acl` + OpenSearch sync jobs. 12b mutates Keycloak membership + Postgres identity mirror. Different APIs, proofs, and failure modes.

### Shared product locks (inherited — do not reopen)

| ID | Lock |
| --- | --- |
| G2 | No Celery/Redis — jobs + poll |
| G3 | File grants = **roles/groups only** (no user-principal file ACL in product) |
| G4 | `viewer` \| `editor` only |
| G5 | Identity writes: Keycloak first, then Postgres |
| G6 | File ACL: Postgres first, then OS sync job |
| G7 / G8 | No role/group rename; no hard user delete |

### Out of both phases (later)

- Access-matrix audit page / CSV export
- “Check access” effective-permissions explorer (optional follow-on after 12b)
- Task 7 multi-worker job locking / dual-write repair CLI
- Per-user `file_acl` grants, folders, link sharing, auto-ACL on upload

### Status

| Phase | Status |
| --- | --- |
| 12a File Access UI | **Done** — see `prompts/summary/12a_file_access_ui.md` |
| 12b Member Assignment UI | **Done** — see `prompts/summary/10b_member_assign.md` |

### Research (shared)

Industry patterns that drove both plans: Google Drive / SharePoint manage-access dialogs, FileCloud ACL visibility, Delbueno RBAC “who / why / blast radius”, Tag & Assign + BrowserStack bulk membership, Confluence group-based grants. Full bibliography lives in each phase file’s appendix only if needed; agents should follow the phase SoT, not re-litigate UX research.

### Changelog

| Date | Change |
| --- | --- |
| 31 Aug 2026 | Combined proposal drafted in this path. |
| 31 Aug 2026 | **Split into two passes:** this index + `12a_file_access_ui.md` + `12b_member_assignment_ui.md`. |
| 31 Aug 2026 | **12b Done** — detail in `prompts/summary/10b_member_assign.md`. |
