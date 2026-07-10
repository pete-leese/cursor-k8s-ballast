// Cursor Cloud Agent remediation — autoCreatePR opens the forward-fix PR.
import { Agent } from "@cursor/sdk";
import { readFileSync } from "node:fs";

function emit(obj) {
  process.stdout.write(JSON.stringify(obj) + "\n");
}

function prUrlFromResult(result) {
  if (!result || typeof result !== "object") return null;
  if (typeof result.prUrl === "string" && result.prUrl) return result.prUrl;
  const branches = result.git?.branches;
  if (Array.isArray(branches)) {
    for (const b of branches) {
      if (typeof b?.prUrl === "string" && b.prUrl) return b.prUrl;
    }
  }
  return null;
}

function prUrlFromText(text) {
  if (!text) return null;
  const m = String(text).match(
    /https:\/\/github\.com\/[^\s)\]\"']+\/pull\/\d+/i,
  );
  return m ? m[0] : null;
}

const apiKey = process.env.CURSOR_API_KEY;
if (!apiKey) {
  emit({ type: "error", text: "CURSOR_API_KEY not set" });
  process.exit(1);
}

let payload = {};
try {
  payload = JSON.parse(readFileSync(0, "utf8") || "{}");
} catch (e) {
  emit({ type: "error", text: `could not parse stdin: ${e}` });
  process.exit(1);
}

const rca = payload.rca;
const issueUrl = payload.issue_url ?? "";
if (!rca) {
  emit({ type: "error", text: "payload.rca is required" });
  process.exit(1);
}

const runtime = (process.env.CURSOR_RUNTIME ?? "cloud").toLowerCase();
const repoUrl = process.env.CURSOR_TARGET_REPO ?? "https://github.com/pete-leese/cursor-k8s-ballast";
const ref = process.env.CURSOR_TARGET_REF ?? "main";
const model = process.env.CURSOR_MODEL ?? "composer-2.5";
const service = rca.service ?? "ingest";
const healthy = rca.resource_change?.previous ?? process.env.BALLAST_HEALTHY_MEMORY ?? "128Mi";
const valuesPath = `deploy/services/${service}.values.yaml`;

const prompt = `You are remediating a production Kubernetes/GitOps incident in this repo.

GitHub issue: ${issueUrl}

ROOT CAUSE ANALYSIS (JSON):
${JSON.stringify(rca, null, 2)}

Tasks:
1. Restore \`resources.limits.memory\` to **${healthy}** in \`${valuesPath}\`.
2. Open a PR against \`${ref}\` titled: fix(${service}): restore memory limit to ${healthy} (Ballast RCA)
3. PR body must link the GitHub issue and summarise the RCA.
4. Do not merge the PR.`;

try {
  const agent = await Agent.create({
    apiKey,
    model: { id: model },
    cloud: {
      repos: [{ url: repoUrl, startingRef: ref }],
      autoCreatePR: true,
    },
  });

  const agentId = agent?.agentId ?? agent?.id ?? "";
  emit({
    type: "status",
    status: "remediation launched",
    text: agent?.url ?? (agentId ? `https://cursor.com/agents/${agentId}` : ""),
    name: agentId || undefined,
  });

  const run = await agent.send(prompt);

  let streamedText = "";
  let prUrl = null;
  try {
    for await (const event of run.stream()) {
      const type = event?.type ?? "";
      if (type === "assistant") {
        const chunks = event?.message?.content ?? [];
        for (const block of chunks) {
          if (block?.type === "text" && block.text) streamedText += block.text;
        }
      }
      // Some SDK builds surface git/PR on status / tool events.
      prUrl =
        prUrl ||
        prUrlFromResult(event) ||
        prUrlFromResult(event?.git ? { git: event.git } : null) ||
        prUrlFromText(event?.text) ||
        prUrlFromText(event?.url);
    }
  } catch {
    /* wait() below is authoritative */
  }

  let result = null;
  try {
    result = await run.wait();
  } catch {
    if (runtime === "cloud") {
      try {
        result = await (
          await Agent.getRun(run.id, { runtime: "cloud", agentId: run.agentId })
        ).wait();
      } catch {
        /* fall through */
      }
    }
  }

  prUrl =
    prUrl ||
    prUrlFromResult(result) ||
    prUrlFromResult(run) ||
    prUrlFromText(result?.result) ||
    prUrlFromText(streamedText);

  if (prUrl) emit({ type: "pr", url: prUrl });
  else emit({ type: "status", status: "pr_pending", text: "run finished without prUrl — caller should discover via GitHub" });

  if (result?.status === "error") {
    emit({ type: "error", text: `remediation run failed: ${result.id}` });
    process.exit(2);
  }

  emit({ type: "complete", text: "remediation agent finished" });
} catch (e) {
  emit({ type: "error", text: String(e?.message ?? e) });
  process.exit(1);
}
