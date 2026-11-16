let practiceSettings = [];
let practiceError = '';
function practiceFields() {
  if (practiceError) return `<p class="error" role="alert">${esc(practiceError)}</p>`;
  const group = (item) => item.key.startsWith('ai_') || item.key === 'flow_includes_ai_assist' ? 'AI assist' : /^auto|^follow_up_after|^reminder_/.test(item.key) ? 'Messaging' : 'Practice';
  const labels = { ai_reply_reading: 'Read unclear replies', ai_interview_assist: 'Interview suggestions', ai_report_assist: 'Report draft and suggestions' };
  const fields = (name) => practiceSettings.filter((item) => group(item) === name).map((item) => {
      const id = `setting-${item.key}`;
      let input;
      if (item.type === 'choice' || item.type === 'select') { // the engine says 'select'
        input = `<select id="${esc(id)}" data-setting="${esc(item.key)}">${(item.options || [])
          .map((option) => {
            const value = typeof option === 'object' ? option.value : option;
            const label = ({ off: 'Off', ask: 'Ask me', auto: 'Automatic' })[value] || (typeof option === 'object' ? option.label : option);
            return `<option value="${esc(value)}" ${String(item.value) === String(value) ? 'selected' : ''}>${esc(label)}</option>`;
          })
          .join('')}</select>`;
      } else if (item.type === 'bool')
        input = `<input id="${esc(id)}" data-setting="${esc(item.key)}" type="checkbox" ${item.value ? 'checked' : ''}>`;
      else
        input = `<input id="${esc(id)}" data-setting="${esc(item.key)}" type="${item.type === 'int' ? 'number' : item.type === 'time' ? 'time' : 'text'}" ${item.type === 'int' ? 'required' : ''} value="${esc(item.value)}" ${item.min == null ? '' : `min="${esc(item.min)}"`} ${item.max == null ? '' : `max="${esc(item.max)}"`}>`;
      return `<label>${esc(labels[item.key] || item.label)} ${input}${item.default === '' || item.default == null || String(item.value) === String(item.default) ? '' : `<small>Default: ${item.type === 'bool' ? (item.default ? 'on' : 'off') : esc(item.default)}</small>`}<span class="error" data-setting-error="${esc(item.key)}" role="alert"></span></label>`;
    })
    .join('');
  return `<form id="practice-settings">${['Practice', 'Messaging', 'AI assist'].filter((name) => practiceSettings.some((item) => group(item) === name)).map((name) => `<section><h2>${name}</h2>${name === 'AI assist' ? '<p>Every step works without AI. These only add a second button.</p>' : ''}<div class="settings-grid">${fields(name)}</div></section>`).join('')}<button type="submit" class="primary">Save settings</button><span id="practice-message" role="status"></span></form>`;
}
async function saveSettings(form) {
  const values = {};
  for (const input of form.querySelectorAll('[data-setting]')) {
    const item = practiceSettings.find((entry) => entry.key === input.dataset.setting);
    values[item.key] = item.type === 'bool' ? input.checked : item.type === 'int' ? Number(input.value) : input.value;
  }
  form.querySelectorAll('[data-setting-error]').forEach((el) => {
    el.textContent = '';
  });
  $('practice-message').textContent = '';
  const changes = H.settingsDiff(practiceSettings, values);
  try {
    if (Object.keys(changes).length) await hmr.api('POST', '/api/settings', changes);
    practiceSettings.forEach((item) => {
      if (Object.hasOwn(changes, item.key)) item.value = changes[item.key];
    });
    $('practice-message').textContent = 'Saved';
  } catch (error) {
    const message = errorText(error);
    const field = [...form.querySelectorAll('[data-setting-error]')]
      .sort((a, b) => b.dataset.settingError.length - a.dataset.settingError.length)
      .find((el) => message.includes(el.dataset.settingError));
    (field || $('practice-message')).textContent = message;
  }
}
let agentMessage = '';
let agentEntries = [];
let addAgentOpen = false;
async function settings() {
  const [c, signIns, data, practice] = await Promise.all([
    hmr.config(),
    hmr.signIns('list'),
    hmr.api('GET', '/api/agents'),
    hmr
      .api('GET', '/api/settings')
      .then((result) => ({ result }))
      .catch((error) => ({ error })),
  ]);
  practiceError = practice.error ? errorText(practice.error) : '';
  practiceSettings = practice.result?.settings || [];
  agentEntries = data.agents;
  const options = (selected) =>
    data.agents
      .filter((a) => a.enabled)
      .map((a) => `<option value="${esc(a.name)}" ${a.name === selected ? 'selected' : ''}>${esc(a.name)}</option>`)
      .join('');
  $('screen').innerHTML = `<h2>Settings</h2>${practiceFields()}
    <section class="card"><h2>Encrypted patient-data backup</h2><p>Back up the database and all files in the configured patient workspace. Store the backup outside that workspace and keep your passphrase safely: it cannot be recovered.</p><div class="actions"><button type="button" data-hmr-backup="create">Back up now</button><button type="button" data-hmr-backup="restore">Restore into a separate folder</button></div><p id="backup-result" role="status"></p></section>
    <section id="saved-sign-ins"><h2>Saved sign-ins</h2><p>Sign-ins save by themselves.</p>
    <p>Stored encrypted for your Windows account on this PC only. Anyone who can use your Windows account can use them.</p>
    <p>PRODA still asks for your 2-step code each time.</p>
    ${
      signIns.available
        ? signIns.entries
            .map(
              (
                entry,
              ) => `<div class="card"><strong>${esc({ mhr: 'My Health Record', emims: 'eMIMS', ppa: 'PPA', amh: 'AMH' }[entry.site])}</strong>
      <p>${entry.saved ? `Username: ${esc(entry.username)} &middot; Origin: ${esc(entry.origin)}` : 'No saved sign-in'}</p>
      <label>Mode<select data-sign-in-mode="${esc(entry.site)}" ${entry.saved ? '' : 'disabled'}>${['off', 'fill', 'auto'].map((mode) => `<option value="${mode}" ${entry.mode === mode ? 'selected' : ''}>${{ off: 'Off', fill: 'Fill', auto: 'Fill and sign in automatically' }[mode]}</option>`).join('')}</select></label>
      ${entry.saved ? `<button data-forget-sign-in="${esc(entry.site)}">Forget</button>` : ''}</div>`,
            )
            .join('')
        : '<p>Encrypted storage is unavailable. Saved sign-ins are disabled.</p>'
    }</section>
    <h2>AI agents</h2><p id="agent-message" role="status">${esc(agentMessage)}</p>
    <table><thead><tr><th>Name</th><th>Type</th><th>Model or command</th><th>Enabled</th><th>Has key</th>
    <th>Route</th><th>Actions</th></tr></thead><tbody>${data.agents
      .map(
        (a) => `<tr><td>${esc(a.name)}
    ${a.type === 'api' ? `<p>Patient information will be sent to this address when you use it: ${esc(a.url)}</p>` : ''}
    </td><td>${esc(a.type)}</td><td>${esc(a.type === 'api' ? a.model : (a.command || []).join(' '))}</td>
    <td>${a.enabled ? 'Yes' : 'No'}</td><td>${a.has_key ? 'Yes' : 'No'}</td><td>${
      a.type === 'cli'
        ? `<label>Route for ${esc(a.name)}<select data-agent-route="${esc(a.name)}">
    <option value="skill" ${a.route === 'skill' ? 'selected' : ''}>Skill</option>
    <option value="prompt" ${a.route !== 'skill' ? 'selected' : ''}>Prompt</option></select></label>`
        : 'Prompt'
    }</td><td>
    <button data-agent-test="${esc(a.name)}" ${a.enabled ? '' : 'disabled'}>Test</button>
    <button data-agent-delete="${esc(a.name)}">Delete</button></td></tr>`,
      )
      .join('')}</tbody></table>
    <form id="agent-select" class="form"><label>Default agent<select name="default" required>
    <option value="">Choose</option>${options(data.default)}</select></label>
    ${['interview_assist', 'report_draft']
      .map(
        (step) => `<label>${esc(H.steps[step] || step)}<select name="${step}">
    <option value="">Use default</option>${options(data.per_step[step])}</select></label>`,
      )
      .join('')}
    <button>Save selections</button></form><button data-add-agent>Add agent</button>
    <form id="agent-form" ${addAgentOpen ? '' : 'hidden'} class="one-off-form"><label>Name<input name="name" required></label>
    <label>Type<select name="type" id="agent-type"><option value="api">API</option>
    <option value="cli">CLI</option></select></label><div id="agent-api">
    <label>Address<input name="url" type="url"></label><label>Model<input name="model"></label>
    <label>Style<select name="style"><option value="openai">OpenAI</option>
    <option value="anthropic">Anthropic</option></select></label>
    <label>Key<input name="key" type="password" autocomplete="new-password"></label></div>
    <div id="agent-cli" hidden><label>Command, one argument per line<textarea name="command"></textarea></label>
    <label>Environment, NAME=value per line<textarea name="env"></textarea></label></div>
    <label><span>Enabled <input type="checkbox" name="enabled" checked></span></label>
    <p class="error" role="alert"></p><button class="primary">Add agent</button></form><details><summary>Technical details</summary><p>Base folder: ${esc(c.base)}</p><p>Engine API: ${esc(c.api)}</p></details>`;
}
function askEncryptedBackupPassphrase(action) {
  // A browser prompt exposes its value as visible plaintext. Use an actual
  // masked, accessible password input and clear the DOM immediately on submit.
  return new Promise(resolve => {
    const panel = document.createElement('dialog');
    panel.setAttribute('aria-label', 'Encrypted HMR backup passphrase');
    panel.innerHTML = `<form method="dialog" class="form">
      <h2>${action === 'create' ? 'Encrypt patient-data backup' : 'Unlock encrypted backup'}</h2>
      <p>Enter a passphrase of at least 12 characters. It is not stored by HMR Desk and cannot be recovered if lost.</p>
      <label>Backup passphrase <input type="password" name="passphrase" autocomplete="off" minlength="12" maxlength="512" required></label>
      <div class="actions"><button class="primary" type="submit">Continue securely</button><button type="button" data-backup-cancel>Cancel</button></div>
    </form>`;
    document.body.appendChild(panel);
    const form = panel.querySelector('form');
    const input = form.elements.namedItem('passphrase');
    let finished = false;
    const finish = value => {
      if (finished) return;
      finished = true;
      input.value = '';
      if (panel.open) panel.close();
      panel.remove();
      resolve(value);
    };
    form.addEventListener('submit', e => {
      e.preventDefault();
      finish(input.value);
    });
    panel.querySelector('[data-backup-cancel]').addEventListener('click', () => finish(null));
    panel.addEventListener('cancel', e => { e.preventDefault(); finish(null); });
    panel.showModal();
    input.focus();
  });
}

async function agentClick(b) {
  if (b.dataset.hmrBackup) {
    const action = b.dataset.hmrBackup;
    const password = await askEncryptedBackupPassphrase(action);
    if (password == null) return true;
    const output = $('backup-result');
    b.disabled = true;
    if (output) output.textContent = 'Processing encrypted backup...';
    try {
      const result = await hmr.encryptedBackup(action, password);
      if (output) output.textContent = result.cancelled ? 'Cancelled' : action === 'create'
        ? 'Backup completed and encrypted' : 'Backup verified and restored into: ' + result.destination;
    } catch (error) {
      if (output) output.textContent = errorText(error);
    } finally {
      b.disabled = false;
    }
    return true;
  }
  if (b.dataset.addAgent !== undefined) {
    addAgentOpen = !addAgentOpen;
    await settings();
    return true;
  }
  const name = b.dataset.agentTest || b.dataset.agentDelete;
  if (!name) return false;
  try {
    if (b.dataset.agentDelete) {
      if (!confirm(`Delete ${name}?`)) return true;
      await hmr.api('POST', '/api/agents/delete', { name });
      agentMessage = 'Agent deleted.';
    } else {
      agentMessage = 'Testing agent?';
      $('agent-message').textContent = agentMessage;
      const result = await hmr.api('POST', '/api/agents/test', { name });
      agentMessage = `${result.ok === false ? 'Test failed' : 'Test reply'}: ${result.reply || ''}`;
    }
  } catch (error) {
    agentMessage = errorText(error);
  }
  await settings();
  return true;
}
async function agentSubmit(form) {
  try {
    const f = new FormData(form);
    if (form.id === 'agent-select') {
      await hmr.api('POST', '/api/agents/select', {
        default: f.get('default'),
        per_step: {
          interview_assist: f.get('interview_assist') || null,
          report_draft: f.get('report_draft') || null,
        },
      });
      agentMessage = 'Selections saved.';
    } else {
      const agent = { name: f.get('name').trim(), type: f.get('type'), enabled: f.has('enabled') };
      if (agent.type === 'api') {
        Object.assign(agent, { url: f.get('url').trim(), model: f.get('model').trim(), style: f.get('style') });
        if (f.get('key')) agent.key = f.get('key');
      } else {
        agent.command = f
          .get('command')
          .split(/\r?\n/)
          .map((s) => s.trim())
          .filter(Boolean);
        agent.env = {};
        for (const line of f.get('env').split(/\r?\n/).filter(Boolean)) {
          const i = line.indexOf('=');
          if (i < 1) throw Error('Environment lines must be NAME=value');
          agent.env[line.slice(0, i)] = line.slice(i + 1);
        }
        agent.stdin = true;
      }
      await hmr.api('POST', '/api/agents', agent);
      agentMessage = 'Agent added.';
      addAgentOpen = false;
    }
    await settings();
  } catch (error) {
    (form.querySelector('.error') || $('agent-message')).textContent = errorText(error);
  }
}
