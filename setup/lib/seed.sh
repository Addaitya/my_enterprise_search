#!/usr/bin/env bash
# Optional ACL seed and proof scripts.

run_seed() {
  info "seeding file ACL for proofs..."
  set +e
  local out
  out="$(
    cd "${REPO_ROOT}/backend"
    uv run python -m scripts.seed_file_acl_for_proofs 2>&1
  )"
  local rc=$?
  set -e
  printf '%s\n' "${out}"

  if (( rc == 0 )); then
    ok "ACL seed"
    return 0
  fi

  # C3: soft-pass when no files exist.
  if printf '%s' "${out}" | grep -qi "no files"; then
    warn "no files to seed — upload first, then re-run with --with-seed"
    return 0
  fi

  die "ACL seed failed" "${EXIT_FAIL}"
}

run_verify_proofs() {
  info "running search_view_proof (needs API + seeded ACL)..."
  warn "proofs that need a running API will fail if servers are not up yet; use --start in another terminal or run proofs after start-dev.sh"
  (
    cd "${REPO_ROOT}/backend"
    uv run python -m scripts.search_view_proof
  ) || die "search_view_proof failed" "${EXIT_FAIL}"
  ok "verify-proofs"
}
