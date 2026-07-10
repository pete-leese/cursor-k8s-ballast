# sdk-runner

Launches a **Cursor Cloud Agent** (via `@cursor/sdk`) to investigate the
k8s-ballast incident and return an RCA that validates against
`ballast/contract.py`. `run.mjs` is the streaming runner used by
`ballast.investigator.CursorInvestigator`; `smoke-test.mjs` is a standalone
end-to-end check.

## Prerequisites

1. **The repo is pushed to GitHub.** The cloud agent clones
   `pete-leese/cursor-k8s-ballast`, so the charts, `topology.yaml`, and the
   incident commit must be present at the ref you target. Push/merge first.
2. **A Cursor paid plan** (cloud runs require it).
3. **Cursor GitHub app** authorised on the target repo (Cursor dashboard →
   Integrations → GitHub → grant access to `cursor-k8s-ballast` only).
4. **API key** — `CURSOR_API_KEY` (Cursor dashboard → Integrations → API Keys).
5. Node 18+.

Cloud runs consume tokens, so each run has a small cost.

## Run

```bash
cd sdk-runner
npm install
CURSOR_API_KEY=...your-key... node smoke-test.mjs
# optional overrides:
#   CURSOR_TARGET_REPO=https://github.com/pete-leese/cursor-k8s-ballast
#   CURSOR_TARGET_REF=main
#   CURSOR_MODEL=composer-2.5
#   CURSOR_RUNTIME=local   # run on this machine so the agent can use the local
#                          # Grafana/Prometheus MCP from .cursor/mcp.json
```

## Verify the contract

```bash
cd ..
./.venv/bin/python -c "from ballast.contract import RCA; \
  RCA.model_validate_json(open('sdk-runner/rca-output.json').read()); print('RCA valid')"
```

## Cloud vs local (reachability)

A **cloud** run happens in Cursor's cloud VM, which **cannot reach your Mac's
`localhost` Prometheus/Grafana**. It investigates from the brief + the repo
(charts, `topology.yaml`, git history). Use **`CURSOR_RUNTIME=local`** if you
want the agent to query the local Grafana/Prometheus MCP servers directly.

## Notes

- `autoCreatePR` is hard-set to `false` — the agent never opens a PR.
- SDK method names match the public launch docs but may drift; the first run's
  `events.jsonl` / `result.json` are the ground truth.
