---
status: implemented
title: Context migration (from first principles)
date: 2026-09-24
notes: Implemented record. Not product truth. prompts/ is frozen — do not edit, move, or delete anything in it.
---

# Context migration plan

**Implemented record.** The checklist below is the spec that was executed. Do not treat it as open work. `prompts/` was not modified. The frozen plan file was not in this checkout, so it was not created under `prompts/`.

**Hard rule:** do **not** change the `prompts/` folder. No edits, no banners, no `git mv`, no deletes, no new files there. The existing tree stays as a frozen original. New agent memory lives in `prompt_2/` plus `.cursor/rules/` (required for Cursor).

Earlier reorg plans (`context_reorg_plan.md`, uncommitted v1 meta files, recovery of `11_opesearch3.7.md` / `native_hybrid_opensearch.md`) are **dropped**. Do not recreate them.

---

## 1. Why the current setup fails

Cursor Agent has **no memory between chats**. It only sees:

1. What Cursor **injects** (project rules, user/team rules, root `AGENTS.md` / `CLAUDE.md`).
2. What the agent **opens** (Read, Grep, `@file`).

Today, `prompts/` is ~38 peer-level markdown files. Plans, ship dumps, and human briefs sit in one pile. Numbering diverges (`9a` plan ↔ `8a` dump, `12a` ↔ `10a`). Many plans still say they are the “source of truth” and still have open checkboxes after the work shipped. An agent that opens the folder treats stale checklists as live work. That is the hallucination problem. Size is a symptom; **no authority boundary** is the cause.

We do **not** fix that by rewriting `prompts/`. We add a small always-on pointer and a new catalog outside that folder. `prompts/` remains the raw archive.

Root `README.md` is the **human** guide (clone, setup, stack). Keep it and keep maintaining it. Agents use `prompt_2/current.md`. When product behavior changes, update **both** so humans and agents stay aligned.

---

## 2. What Cursor actually supports (use only this)

From Cursor’s rules model ([docs](https://cursor.com/docs/rules)):

| Mechanism | When it enters context | Use here |
| --- | --- | --- |
| `.cursor/rules/*.mdc` + `alwaysApply: true` | **Every** Agent chat. `globs` / `description` ignored. | One tiny pointer rule. |
| `.mdc` + `globs` + `alwaysApply: false` | When a matching file is in context. | Fence the frozen `prompts/**` tree. |
| `.mdc` + `description`, no globs | Agent may pull it if the description matches. | Not needed. |
| `.mdc` with neither | Only if someone `@`-mentions it. | Not needed. |
| Root `AGENTS.md` / `CLAUDE.md` | **Every** Agent chat (no off switch). | **Do not add.** |
| Nested `AGENTS.md` | When working under that directory. | **Do not add** under `prompts/`. |
| `@path` inside a rule | Pulls that file into the rule’s context. | **Do not `@` `current.md`, README, or the index.** Point at paths in prose. |
| Skills | Description always visible; body on use. | Out of scope. |
| YAML on random `.md` | **Ignored by Cursor.** | Not used on frozen `prompts/` files. |

Official guidance: keep rules short; **reference files, don’t copy them**; don’t duplicate the repo.

Rules must be `.mdc` under `.cursor/rules/`. Plain `.md` there is ignored. Rules do not affect Tab or inline edit.

---

## 3. Target design

Always-on surface: **one ~15-line rule**. Everything else is cold until the agent opens it.

```
.cursor/rules/
  memory.mdc                 # Always Apply — pointers + landmines
  prompts-are-cold.mdc       # globs: prompts/** — frozen archive, not live truth

prompt_2/                    # NEW — only place we write agent memory
  README.md                  # human: how prompt_2 works; prompts/ is frozen
  current.md                 # agent product truth
  index.md                   # catalog of frozen prompts/ files (topic labels + old paths)

prompts/                     # FROZEN — do not touch
  cursor_summary/            # original plans (keep numbers)
  summary/                   # original ship dumps
  instructions/              # original human briefs
  02_active/                 # this plan file only (leave it)
```

Do **not** copy the 38 files into `prompt_2/`. That would double the pile. The index **points at** the existing paths. Topic names live in the index as labels (`auth` plan = `prompts/cursor_summary/4_auth_setup.md`).

**Audience split (locked):**

| Doc | For | Role |
| --- | --- | --- |
| Root `README.md` | Humans | Clone, setup, stack, Now / Not yet. Keep and maintain. |
| `prompt_2/current.md` | Agents | Live product SoT. Read before changing product behavior. |
| `prompt_2/README.md` | Humans | How agent memory is laid out. |
| `prompts/**` | Archive | Frozen originals. Not live truth. |

When a ship changes product behavior, update `prompt_2/current.md` **and** root `README.md`. Do not edit files under `prompts/` to “fix” old checkboxes.

**Unfinished product work that exists in git** (leave in place, list in the index as `active`):

- `prompts/instructions/2_Ingestion_pipeline.md`
- `prompts/cursor_summary/12_ingestion_pipeline_proposal.md`

Native hybrid / 3.9 and Task 7 stay “Not yet” in `current.md` (and the human README). Do not invent plans or recover missing files.

---

## 8. Tasks (executed)

### T0 — Preflight

- [x] Working tree was otherwise clean. The frozen plan file was not in this checkout, so it was not created under `prompts/`.
- [x] Do **not** delete, edit, or `git mv` anything under `prompts/`.
- [x] Catalog sources in §5 exist. No missing source was invented.
- [x] `mkdir -p .cursor/rules prompt_2`

### T1 — Create new surface only

- [x] Write `.cursor/rules/memory.mdc` (§4.1).
- [x] Write `.cursor/rules/prompts-are-cold.mdc` (§4.2).
- [x] Write `prompt_2/current.md` (§4.3). Do not gut or replace root `README.md`.
- [x] Write `prompt_2/README.md` (§4.4).
- [x] Write `prompt_2/index.md` (§4.5 / §6).

There is **no T2 move step.**

### T3 — Human README layout line only

- [x] Root `README.md` layout line only.

Do **not** change `backend/scripts/ingest_proof.py` or `ingest_folder_proof.py`.

### T4 — Do not remove old dirs

`prompts/cursor_summary/`, `prompts/summary/`, `prompts/instructions/` stay. `prompts/02_active/` was not present in this checkout and was not created.

### T5 — Verify

- [x] `memory.mdc` is `alwaysApply: true` and does **not** `@`-include `current.md`, README, or `index.md`.
- [x] `prompts-are-cold.mdc` globs `prompts/**`.
- [x] `prompt_2/current.md` exists and has no task checkboxes.
- [x] Root `README.md` still exists as the human guide.
- [x] No root `AGENTS.md` / `CLAUDE.md` was added.
- [x] Every path in `prompt_2/index.md` exists.
- [x] `git status` shows **no** modifications under `prompts/`. No new files under `prompts/`.
- [x] Old `prompts/` dirs still exist with the same files.

### T6 — Close this plan (without touching `prompts/`)

- [x] This file is the implemented record. The frozen plan was not moved or deleted.

---

## 9. Out of scope

- Any write under `prompts/`.
- Application behavior (except the root README layout line).
- Copying or renaming the archive files.
- Inventing Task 7, native-hybrid, or any missing file.
- Backend/frontend coding-convention rules.
- Skills, MCP, user rules, team rules.
