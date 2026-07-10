#!/usr/bin/env bash
# Shared helpers for GitOps PR workflow (break / fix / remediate).
set -euo pipefail

git_pr_require_gh() {
  if ! command -v gh >/dev/null 2>&1; then
    echo "ERROR: gh CLI is required. Install: https://cli.github.com" >&2
    exit 1
  fi
  export GH_HOST="${GH_HOST:-github.com}"
  if gh api user -q .login >/dev/null 2>&1; then
    return 0
  fi
  local status
  status="$(gh auth status -h github.com 2>&1 || true)"
  if echo "${status}" | grep -qiE 'keyring|invalid|forbidden'; then
    echo "ERROR: gh cannot use the stored github.com token from this process (keyring/token)." >&2
    echo "       In your terminal: gh auth refresh -h github.com" >&2
    echo "       Or set GH_TOKEN in .env for the Ballast API." >&2
    exit 1
  fi
  echo "ERROR: gh is not authenticated for github.com API calls." >&2
  echo "       Run: gh auth refresh -h github.com  (or set GH_TOKEN)" >&2
  exit 1
}

git_pr_base_branch() {
  echo "${BALLAST_BASE_BRANCH:-main}"
}

git_pr_create_branch() {
  local prefix="$1"
  local service="$2"
  local base
  base="$(git_pr_base_branch)"
  local branch="${prefix}/${service}-$(date -u +%Y%m%d-%H%M%S)"
  git fetch -q origin "${base}"
  git checkout -q -B "${branch}" "origin/${base}"
  echo "${branch}"
}

git_pr_commit_push() {
  local branch="$1"
  local message="$2"
  shift 2
  git add "$@"
  git commit -q -m "${message}"
  git push -q -u origin "${branch}"
}

git_pr_open() {
  local branch="$1"
  local title="$2"
  local body="$3"
  local base
  base="$(git_pr_base_branch)"
  gh pr create \
    --base "${base}" \
    --head "${branch}" \
    --title "${title}" \
    --body "${body}"
}

git_pr_maybe_merge() {
  local pr_url="$1"
  if [[ "${BALLAST_AUTO_MERGE:-}" == "1" ]]; then
    echo "==> BALLAST_AUTO_MERGE=1 — merging PR into $(git_pr_base_branch)"
    gh pr merge "${pr_url}" --squash --delete-branch || gh pr merge "${pr_url}" --squash
  else
    echo "==> Merge the PR when ready — ArgoCD syncs from $(git_pr_base_branch) after merge"
    echo "    gh pr merge ${pr_url} --squash"
  fi
}
