import { esc, icon } from "./workspace-core.js";

const AGENTS = [
  { name: "Regulatory prosecutor", role: "Check statutory controls", thinking: "Considering the corridor and applicable controls…", working: "Organizing potential compliance issues…" },
  { name: "Defense counsel", role: "Review supporting evidence", thinking: "Considering evidence and possible mitigations…", working: "Preparing the response to the findings…" },
  { name: "Chief compliance officer", role: "Bring the assessment together", thinking: "Considering both sides of the assessment…", working: "Preparing the decision summary…" },
];
const STAGES = ["Starting", "Thinking", "Working", "Finished"];

export class AgentDemo {
  constructor(onChange = () => {}, onLog = () => {}) {
    this.onChange = onChange;
    this.onLog = onLog;
    this.busy = false;
    this.runId = 0;
    this.rows = AGENTS.map(() => ({ stage: "Ready", message: "Ready for the next request." }));
  }
  update(index, stage, message) {
    this.rows[index] = { stage, message };
    this.onChange();
    this.onLog("info", `Workflow · ${AGENTS[index].name}: ${stage}`);
  }
  async run(operation = async () => {}) {
    if (this.busy) throw new Error("A workflow is already running.");
    this.busy = true;
    const id = ++this.runId;
    this.rows = AGENTS.map(() => ({ stage: "Starting", message: "Starting the workflow…" }));
    this.onChange();
    const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
    const animate = async () => {
      for (let index = 0; index < AGENTS.length; index++) {
        for (const [stage, message] of [
          ["Thinking", AGENTS[index].thinking],
          ["Working", AGENTS[index].working],
        ]) {
          await pause(650);
          if (id !== this.runId) return;
          this.update(index, stage, message);
        }
        if (index < AGENTS.length - 1) {
          await pause(350);
          if (id !== this.runId) return;
          this.update(index, "Finished", "Stage complete. Findings appear in the request result.");
        }
      }
    };
    try {
      const [result] = await Promise.all([Promise.resolve().then(operation), animate()]);
      if (id === this.runId) this.update(2, "Finished", "Stage complete. Review the request result and transaction status.");
      return result;
    } catch (error) {
      this.runId++;
      this.rows = this.rows.map(row => row.stage === "Finished" ? row : { stage: "Stopped", message: "The request failed. Check execution logs for the actual error." });
      this.onLog("error", "Workflow stopped because the request failed.");
      throw error;
    } finally {
      this.busy = false;
      this.onChange();
    }
  }
}

export function agentDemoView(demo) {
  return `<section class="panel agent-demo" aria-label="Agent workflow"><div class="panel-head"><h2>${icon("activity")}Agent workflow</h2><button type="button" class="icon-button" data-action="agent-demo" aria-label="Replay agent animation" ${demo.busy ? "disabled" : ""}>${icon("cycle")}</button></div><div class="agent-demo-grid">${AGENTS.map((agent, index) => {
    const row = demo.rows[index];
    const current = STAGES.indexOf(row.stage);
    return `<article class="agent-demo-card ${row.stage.toLowerCase()}" data-demo-agent="${index}"><div class="agent-demo-title"><span class="agent-demo-orb" aria-hidden="true">${row.stage === "Finished" ? icon("check") : icon("cycle")}</span><div><h3>${esc(agent.name)}</h3><p class="text-note">${esc(agent.role)}</p></div><span class="badge" data-demo-stage>${esc(row.stage)}</span></div><ol class="agent-demo-stages" aria-label="Workflow stages">${STAGES.map((stage, i) => `<li ${i === current ? 'aria-current="step"' : ""} class="${current >= i ? "reached" : ""}">${esc(stage)}</li>`).join("")}</ol><p class="agent-demo-message" role="status">${esc(row.message)}${["Thinking", "Working"].includes(row.stage) ? '<span class="agent-thinking-dots" aria-hidden="true"><i></i><i></i><i></i></span>' : ""}</p></article>`;
  }).join("")}</div></section>`;
}
