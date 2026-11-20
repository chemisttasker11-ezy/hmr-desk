#!/usr/bin/env node
// Runs a JSON plan against the real stdio MCP server (hmr-desk-mcp.js) in this environment, so a test run is a repeatable
// file instead of manual clicking. Usage: node run-plan.js plan.json outdir
// Plan: {"steps":[{"name":"...","tool":"app_ui_fill","args":{"value":"x"},"find":{"label":"Name"},"save":"file","expect":"text","optional":false}]}
//  - find: picks the ref from the most recent app_ui_snapshot step; every given property (label, type, id, tag, text, or data.<name>)
//    must match exactly one control, otherwise the plan stops. A plan re-snapshots by including another app_ui_snapshot step.
//  - save: writes the tool result to outdir/<file>; images are decoded to PNG files. Nothing else is written, and tokens are never read here.
//  - The run stops at the first failing step (tool error, a tool-level {ok:false}/error result, or failed expect) unless the step is marked optional.
//    "allowToolFailure": true accepts a tool-level failure; "require" demands one.
// The server applies its own refusals (sending, authorisation, sensitive fields); this runner adds none and removes none.
const { spawn } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');

// A tool can answer successfully at the transport level and still report {"ok":false,"error":...} (for example a screen that
// cannot open yet). That is a failed step, not a pass. A step may opt out with "allowToolFailure": true, or require the failure
// with "allowToolFailure": "require".
function toolLevelFailure(text) {
  let value; try { value = JSON.parse(text); } catch { return ''; }
  if (!value || typeof value !== 'object' || Array.isArray(value)) return '';
  if (value.ok === false) return String(value.error || 'ok is false');
  if (typeof value.error === 'string' && value.error) return value.error;
  return '';
}

async function run(planPath, outDir, serverPath = path.join(__dirname, 'hmr-desk-mcp.js')) {
  const plan = JSON.parse(fs.readFileSync(planPath, 'utf8'));
  if (!plan || !Array.isArray(plan.steps) || !plan.steps.length) throw Error('plan has no steps');
  fs.mkdirSync(outDir, { recursive: true });
  const child = spawn(process.execPath, [serverPath], { stdio: ['pipe', 'pipe', 'inherit'], env: process.env });
  const lines = []; let buf = '';
  child.stdout.on('data', (d) => { buf += d; let i; while ((i = buf.indexOf('\n')) >= 0) { lines.push(JSON.parse(buf.slice(0, i))); buf = buf.slice(i + 1); } });
  let id = 0;
  const rpc = async (method, params) => {
    const mine = ++id;
    child.stdin.write(JSON.stringify({ jsonrpc: '2.0', id: mine, method, params }) + '\n');
    for (let k = 0; k < 1200; k++) { const hit = lines.find((l) => l.id === mine); if (hit) return hit; await new Promise((r) => setTimeout(r, 25)); }
    throw Error('no reply from the MCP server');
  };
  const report = [];
  let snapshot = null, failed = false;
  try {
    await rpc('initialize', { protocolVersion: '2024-11-05', capabilities: {}, clientInfo: { name: 'run-plan', version: '1' } });
    for (const [n, step] of plan.steps.entries()) {
      const label = step.name || step.tool;
      const args = { ...(step.args || {}) };
      let problem = null, summary = '';
      try {
        if (step.find) {
          if (!snapshot) throw Error('find needs an earlier app_ui_snapshot step');
          const match = snapshot.controls.filter((c) => Object.entries(step.find).every(([k, v]) => (k.startsWith('data.') ? c.data && c.data[k.slice(5)] : c[k]) === v));
          if (match.length !== 1) throw Error('find matched ' + match.length + ' controls, expected exactly 1: ' + JSON.stringify(step.find));
          args.ref = match[0].ref;
        }
        const reply = await rpc('tools/call', { name: step.tool, arguments: args });
        const result = reply.result;
        if (!result) throw Error(JSON.stringify(reply.error || reply));
        const text = result.content.filter((c) => c.type === 'text').map((c) => c.text).join('\n');
        if (result.isError) throw Error(text);
        const toolFailure = toolLevelFailure(text);
        if (toolFailure && !step.allowToolFailure) throw Error('tool-level failure (transport ok): ' + toolFailure);
        if (!toolFailure && step.allowToolFailure === 'require') throw Error('expected a tool-level failure but the tool reported success');
        const image = result.content.find((c) => c.type === 'image');
        if (image) {
          const file = path.join(outDir, step.save || `step${n + 1}.png`);
          fs.writeFileSync(file, Buffer.from(image.data, 'base64'));
          summary = 'image saved: ' + path.basename(file) + ' (' + Buffer.byteLength(image.data, 'base64') + ' bytes)';
        } else {
          if (step.tool === 'app_ui_snapshot') {
            snapshot = JSON.parse(text);
            summary = `snapshot ${snapshot.snapshot} screen=${snapshot.screen} controls=${snapshot.controls.length} blocked=${snapshot.controls.filter((c) => c.blocked).length} sensitive=${snapshot.controls.filter((c) => c.sensitive).length}`;
          } else summary = text.length > 300 ? text.slice(0, 300) + '...' : text;
          if (step.save) fs.writeFileSync(path.join(outDir, step.save), text);
        }
        if (step.expect && !text.includes(step.expect) && !image) throw Error('expected text not found: ' + step.expect);
      } catch (error) { problem = error.message; }
      report.push({ step: n + 1, name: label, ok: !problem, summary, problem });
      console.log(`${problem ? 'FAIL' : 'ok  '} ${n + 1}. ${label}${problem ? ': ' + problem : ' - ' + summary}`);
      if (problem && !step.optional) { failed = true; break; }
    }
  } finally { child.stdin.end(); setTimeout(() => child.kill(), 2000).unref(); }
  fs.writeFileSync(path.join(outDir, 'plan-report.json'), JSON.stringify(report, null, 2));
  return { failed, report };
}
module.exports = { run, toolLevelFailure };
if (require.main === module) {
  const [plan, out] = process.argv.slice(2);
  if (!plan || !out) { console.error('usage: node run-plan.js plan.json outdir'); process.exit(2); }
  run(plan, out).then((r) => process.exit(r.failed ? 1 : 0), (e) => { console.error(e.message); process.exit(2); });
}
