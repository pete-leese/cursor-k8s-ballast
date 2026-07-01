// Cursor Agent SDK smoke-test for k8s-ballast.
//
// Proves end-to-end that a Cursor *cloud* agent can clone this repo, investigate
// the payments CrashLoopBackOff incident (bad chart bump lowering the memory
// limit), reason about rollback vs forward-fix using topology.yaml for blast
// radius, and return RCA JSON that matches ballast/contract.py.
//
// It writes:
//   events.jsonl    - every streamed event, verbatim
//   result.json     - the full final run object from getRun().wait()
//   rca-output.json - best-effort extraction of the agent's RCA JSON
//
// Run:  cd sdk-runner && npm install && CURSOR_API_KEY=... node smoke-test.mjs
//
// Requires: Cursor paid plan, the Cursor GitHub app authorised on the target
// repo, and the repo pushed to GitHub (the cloud VM clones it from there).

import { Agent } from "@cursor/sdk";
import { appendFileSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const __dir = dirname(fileURLToPath(import.meta.url));

const apiKey = process.env.CURSOR_API_KEY;
if (!apiKey) {
  console.error("error: set CURSOR_API_KEY (cursor.com -> Dashboard -> Integrations -> API Keys)");
  process.exit(1);
}
const repoUrl = process.env.CURSOR_TARGET_REPO ?? "https://github.com/pete-leese/cursor-k8s-ballast";
const ref = process.env.CURSOR_TARGET_REF ?? "main";
const model = process.env.CURSOR_MODEL ?? "composer-2";

const schema = readFileSync(join(__dir, "..", "schema", "rca.schema.json"), "utf8");

const prompt = `You are a codebase/infrastructure investigator, not a code generator.
Investigate a production incident in the "payments" Kubernetes service in this repo.

Incident brief:
- Alert: BallastServiceCrashLooping fired for the payments container in namespace ballast.
- Symptom: payments pods are OOMKilled on startup (exit code 137) and stuck in CrashLoopBackOff.
- Suspected cause: a recent Helm chart bump lowered resources.limits.memory below the
  service's startup memory ballast. Look in charts/ballast-service and
  deploy/services/payments.values.yaml, and the recent git history of that file.

Tasks:
1. Identify the chart/values change that explains the crash (which field regressed, old vs new).
2. Confirm the rollout that shipped the change correlates in time with the alert.
3. Use topology.yaml (blast_radius) to reason about whether a full rollback or a targeted
   forward-fix is safer, and give the exact remediation.

Return ONLY a single JSON object that validates against this JSON Schema. No prose,
no markdown code fences, JSON only:

${schema}`;

function extractText(node) {
  if (!node) return "";
  if (typeof node === "string") return node;
  if (typeof node.text === "string") return node.text;
  if (typeof node.delta === "string") return node.delta;
  if (typeof node.content === "string") return node.content;
  if (Array.isArray(node.content)) return node.content.map(extractText).join("");
  if (node.message) return extractText(node.message);
  return "";
}

console.error(`launching cloud agent on ${repoUrl}@${ref} (model: ${model})`);

const agent = await Agent.create({
  apiKey,
  model: { id: model },
  cloud: { repos: [{ url: repoUrl, startingRef: ref }], autoCreatePR: false },
});

console.error(`agent id: ${agent?.id ?? "?"}`);
console.error(`view in Cursor: ${agent?.url ?? "https://cursor.com/agents"}`);

const run = await agent.send(prompt);

const eventsPath = join(__dir, "events.jsonl");
writeFileSync(eventsPath, "");

let assistantText = "";
for await (const event of run.stream()) {
  appendFileSync(eventsPath, JSON.stringify(event) + "\n");
  if ((event?.type ?? "") === "assistant") assistantText += extractText(event);
  console.error(`[event ${event?.type ?? "unknown"}] ${JSON.stringify(event).slice(0, 200)}`);
}

const result = await (
  await Agent.getRun(run.id, { runtime: "cloud", agentId: run.agentId })
).wait();
writeFileSync(join(__dir, "result.json"), JSON.stringify(result, null, 2) + "\n");
console.error(`\nrun status: ${result?.status ?? "unknown"}`);

const finalText = (extractText(result?.messages?.at?.(-1)) || extractText(result) || assistantText).trim();
const a = finalText.indexOf("{");
const b = finalText.lastIndexOf("}");
const json = a >= 0 && b > a ? finalText.slice(a, b + 1) : finalText;
writeFileSync(join(__dir, "rca-output.json"), json + "\n");

console.error("\nwrote events.jsonl, result.json, rca-output.json");
console.error("validate the RCA with:");
console.error(
  `  ../.venv/bin/python -c "from ballast.contract import RCA; RCA.model_validate_json(open('sdk-runner/rca-output.json').read()); print('RCA valid')"`
);
