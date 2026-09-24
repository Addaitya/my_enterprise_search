# Catalog

`prompts/` is a frozen archive. Do not edit those files. Corrections live only in this index.

**Live (agents):** `prompt_2/current.md` — product truth. Read it before changing product behavior.

**Live (humans):** `README.md` — clone, setup, and stack. Not the agent source of truth.

The frozen plan file was not in this checkout, so it is not listed. The implemented record is `prompt_2/context_migration.md`.

## Briefs

| Topic | Status | Path | Topic sentence |
| --- | --- | --- | --- |
| setup brief | historical | `prompts/instructions/1_setup_project.md` | Early project setup brief. Search layer is OpenSearch, not openai. Do not edit the file. |
| ingestion brief | active | `prompts/instructions/2_Ingestion_pipeline.md` | Human brief for the ingestion pipeline. Connectors are not built. |

## Active

| Topic | Status | Path | Topic sentence |
| --- | --- | --- | --- |
| multi-connector ingestion | active | `prompts/cursor_summary/12_ingestion_pipeline_proposal.md` | Proposal for multi-connector ingestion. Still unfinished. |

## Plans

| Topic | Status | Path | Topic sentence |
| --- | --- | --- | --- |
| setup project | historical | `prompts/cursor_summary/1_setup_project.md` | Plan for the initial project setup. |
| project overview | historical | `prompts/cursor_summary/2_project_overview_tasks.md` | Task overview. Checkboxes in this file are stale. |
| auth | historical | `prompts/cursor_summary/4_auth_setup.md` | Auth setup plan. Superseded for JWT keys (PEM / 2.19). |
| data model | historical | `prompts/cursor_summary/5_data_setup.md` | Data-model plan for identity, files, and ACL. |
| search platform | historical | `prompts/cursor_summary/6_search_setup.md` | Plan for the OpenSearch search platform. |
| ingest HTTP | historical | `prompts/cursor_summary/7_ingest_api.md` | Plan for the resumable HTTP ingest API. |
| search view | historical | `prompts/cursor_summary/8_search_view_api.md` | Plan for search plus View and Open. |
| admin panel index | historical | `prompts/cursor_summary/9_admin_panel.md` | Index plan for the admin panel. |
| admin identity | historical | `prompts/cursor_summary/9a_admin_panel.md` | Plan for admin identity (users, roles, groups). |
| admin file ACL | historical | `prompts/cursor_summary/9b_admin_panel.md` | Plan for admin file ACL grants. |
| setup script | historical | `prompts/cursor_summary/10_setup.md` | Plan for the local setup script. |
| ACL UI index | historical | `prompts/cursor_summary/12_acl_ui.md` | Index plan for the ACL UI. |
| file access UI | historical | `prompts/cursor_summary/12a_file_access_ui.md` | Plan for the file-access UI. “12b not started” in the matching dump is wrong; 12b did ship (see `prompts/summary/10b_member_assign.md`). |
| member assignment UI | historical | `prompts/cursor_summary/12b_member_assignment_ui.md` | Plan for the member-assignment UI. It did ship. |
| dashboard | historical | `prompts/cursor_summary/13_changes.md` | Plan for the admin dashboard. |
| ingest folder CLI | historical | `prompts/cursor_summary/14_ingestion_script.md` | Plan for the ops folder ingest CLI. |
| hybrid search workaround | historical | `prompts/cursor_summary/hybrid_search_issue_sol.md` | Plan for the client-side hybrid workaround on OpenSearch 3.8. |
| OpenSearch 3.8 upgrade | historical | `prompts/cursor_summary/update_opensearch_version.md` | Plan for the OpenSearch 3.8 upgrade, including the JWT key change off PEM. |

## Shipped

| Topic | Status | Path | Topic sentence |
| --- | --- | --- | --- |
| auth | shipped | `prompts/summary/2_auth_layer.md` | Ship dump for auth. Still documents PEM; superseded by the 3.8 upgrade plan. |
| data model | shipped | `prompts/summary/3_data_modeling.md` | Ship dump for the Postgres data model. |
| search platform | shipped | `prompts/summary/4_search_layer.md` | Ship dump for the OpenSearch search layer. |
| ingest HTTP | shipped | `prompts/summary/5_local_ingestion_setup.md` | Ship dump for local HTTP ingestion. |
| search view (partial) | shipped | `prompts/summary/6_search_view.md` | Search-half only. Full Task 5 is `prompts/summary/7_search_view_api.md`. |
| search view (full) | shipped | `prompts/summary/7_search_view_api.md` | Full ship dump for search, View, and Open. |
| admin identity | shipped | `prompts/summary/8a_admin_panel.md` | Ship dump for admin identity. |
| admin file ACL | shipped | `prompts/summary/8b_admin_panel.md` | Ship dump for admin file ACL. |
| setup script | shipped | `prompts/summary/9_setup.md` | Ship dump for the setup script. |
| file access UI (canonical 12a) | shipped | `prompts/summary/10a_acl_ui_update.md` | Canonical ship record for the file-access UI. “12b not started” here is wrong; 12b did ship (see `prompts/summary/10b_member_assign.md`). |
| member assignment UI | shipped | `prompts/summary/10b_member_assign.md` | Ship dump for member assignment. This is the record that 12b shipped. |
| dashboard | shipped | `prompts/summary/13_changes.md` | Ship dump for the admin dashboard. |
| ingest folder CLI | shipped | `prompts/summary/14_ingest_script.md` | Ship dump for the folder ingest CLI. |
| hybrid search workaround | shipped | `prompts/summary/hybrid_search_issue.md` | Ship dump for the client-side hybrid workaround. |

## Junk

| Topic | Status | Path | Topic sentence |
| --- | --- | --- | --- |
| empty current tasks | junk | `prompts/cursor_summary/3_current_tasks.md` | Empty file. Leave it in place. |
| empty version placeholder | junk | `prompts/summary/opesearch_version_update.md` | Empty placeholder. Leave it in place. |
| early project note | junk | `prompts/summary/1_high_level_project_info.md` | Early note (including “viewer/onwer”). Leave it in place. |
| file access UI duplicate | junk | `prompts/summary/12a_file_access_ui.md` | Short duplicate of `prompts/summary/10a_acl_ui_update.md`. Canonical ship record stays the 10a dump. |
