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
async function recordsCardLoad() {
  const output = $('records-result'), pick = $('records-patient');
  if (!output) return;
  try {
    const status = await hmr.api('GET', '/api/records/status');
    const list = await hmr.api('GET', '/api/patients');
    if (pick) pick.replaceChildren(...[{id: '', name: 'Choose records to export'}, ...(list.patients || []), {id: 0, name: 'Shared records (all patients)'}].map(p => { const o = document.createElement('option'); o.value = String(p.id); o.textContent = p.name; return o; }));
    output.textContent = status.records_in_encrypted_store + ' records in the encrypted store. ' +
      status.plain_copies_matching_store + ' plain copies still on disk match them and ' + status.plain_files_differing_or_not_stored +
      ' plain files differ or are not stored yet. Saved records are not protected while plain copies remain.';
  } catch (error) { output.textContent = errorText(error); }
}
async function settings() {
  const [c, signIns, data, practice, health] = await Promise.all([
    hmr.config(),
    hmr.signIns('list'),
    hmr.api('GET', '/api/agents'),
    hmr
      .api('GET', '/api/settings')
      .then((result) => ({ result }))
      .catch((error) => ({ error })),
    hmr.api('GET', '/api/health').catch(error => ({error:errorText(error)})),
  ]);
  practiceError = practice.error ? errorText(practice.error) : '';
  practiceSettings = practice.result?.settings || [];
  agentEntries = data.agents;
  const options = (selected) =>
    data.agents
      .filter((a) => a.enabled)
      .map((a) => `<option value="${esc(a.name)}" ${a.name === selected ? 'selected' : ''}>${esc(a.name)}</option>`)
      .join('');
  const caps = health?.capabilities || {};
  const aiDisabled = !practiceSettings.some(item =>
    (item.key === 'ai_interview_assist' || item.key === 'ai_report_assist') &&
    item.value !== 'off' && item.value !== false);
  const ready = health?.ready === true;
  $('screen').innerHTML = `<h2>Settings</h2>${localReferencePanel()}${practiceFields()}
    <section class="card" aria-label="Offline and external service capabilities">
      <h2>Standalone capabilities and online services</h2>
      <p role="status">Local engine: ${ready ? 'Ready and authenticated' : 'Unavailable — ' + esc(health?.error || 'check the engine')}.
      PDF converter: ${caps.pdf_converter_available ? 'bundled and detected' : 'not available; Word drafts remain available'}.
      Owner-approved report layout: ${caps.approved_template_available ? 'registered (visual acceptance still required)' : 'not yet registered; output is provisional'}.</p>
      <p>Manual HMR: ${ready && caps.manual_hmr ? 'available independently of online services' : 'not currently available'}.
      Clinical AI: ${aiDisabled ? 'off in interview and report settings' : 'optional assisted mode enabled; check privacy controls'}.
      OCR: ${caps.ocr_component_bundled ? 'Windows helper bundled; scanned text requires visual confirmation' : 'unavailable; source/manual review remains available'}.</p>
      <p>External optional MIMS, AMH, PRODA/My Health Record, PPA and SMS each require internet and separate authorised accounts/licences.
      ${!navigator.onLine ? 'This device currently reports offline. Online services are unavailable.' :
        'The device reports possible network connectivity; portal authentication and licences have not been verified.'}
      Their unavailability must not block the manual HMR workflow. Authorised identifying SMS remains separate from clinical AI.</p>
    </section>
    <section class="card"><h2>Data protection</h2><p>The patient database is encrypted on this PC. Its key is tied to your Windows user. The recovery key lets you open the database on a new PC after restoring a backup. Store it somewhere safe and separate, such as a password manager or a printed copy.</p><div class="actions"><button type="button" data-storage="reveal">Show recovery key</button><button type="button" data-storage="confirm">I have stored the recovery key</button><button type="button" data-storage="rotate">Make a new recovery key</button></div><p id="storage-result" role="status"></p></section>
    <section class="card"><h2>Saved clinical records</h2><p>Saved interview, report, medicine, follow-up and pathology records are being moved into the encrypted database. Until the tracked plain copies in patient folders and shared storage are removed they are NOT protected, and Word, PDF and source documents are not encrypted by the app. You can export a readable copy of one patient's records or the shared corrections and history plan (which may cover several patients). The exported copy is outside the app's encryption.</p><div class="actions"><button type="button" data-records-refresh>Check record storage</button><select id="records-patient" aria-label="Patient to export"></select><button type="button" data-records-export>Export records...</button><button type="button" data-records-retire>Remove verified plain copies...</button></div><p id="records-result" role="status"></p></section>
    <section class="card"><h2>Encrypted patient-data backup</h2><p>Back up the database and all files in the configured patient workspace. Store the backup outside that workspace and keep your passphrase safely: it cannot be recovered.</p><div class="actions"><button type="button" data-hmr-backup="create">Back up now</button><button type="button" data-hmr-backup="preview">Verify and preview a backup</button><button type="button" data-hmr-backup="restore">Restore into a separate folder</button><button type="button" data-restored-activate>Activate a verified isolated restored dataset (with rollback)</button><button type="button" data-restored-rollback>Roll back to previous data</button></div><p id="backup-result" role="status"></p></section>
    <section class="card"><h2>Owner-approved HMR report template</h2>
      <p>The full layout must be approved by the owner, have matching short and long example reports, and include named HMR placeholders. Brainstorming PDFs and patient case reports are not a substitute.</p>
      <label>Template version<input id="hmr-template-version" maxlength="80" placeholder="Owner release version"></label>
      <label>Approving owner<input id="hmr-template-owner" maxlength="150" placeholder="Person explicitly authorising layout"></label>
      <label><input id="hmr-template-authorised" type="checkbox"> I have the owner's permission to use this editable DOCX and its fonts/letterhead for HMR Desk.</label>
      <button type="button" data-template-register>Choose and register approved Word template</button>
      <p id="template-register-status" role="status"></p>
    </section>
    <section class="card"><h2>Migrate existing patient workspace</h2><p>Move to a different local drive or folder without losing the originals. The clinical engine is stopped for the verified copy, an encrypted recovery backup is created first, and HMR Desk restarts after updating its workspace.</p><button type="button" data-workspace-migrate>Migrate current workspace safely</button><p role="status" id="migration-result"></p></section>
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
  refreshLocalReferenceStatus();
  recordsCardLoad();
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
  if (b.dataset.templateRegister !== undefined) {
    const output = $('template-register-status');
    const version = $('hmr-template-version')?.value?.trim() || '';
    const approved_by = $('hmr-template-owner')?.value?.trim() || '';
    if (!version || approved_by.length < 3 || !$('hmr-template-authorised')?.checked) {
      if (output) output.textContent = 'Enter the version and approving owner, then confirm permission to use the editable layout.';
      return true;
    }
    b.disabled = true;
    if (output) output.textContent = 'Validating approved DOCX structure and exact checksum...';
    try {
      const response = await hmr.registerOwnerTemplate({
        version,approved_by,owner_authorised:true
      });
      if (output) output.textContent = response.cancelled
        ? 'Template registration cancelled'
        : 'Approved template version ' + response.version + ' registered. SHA256: ' +
          response.sha256 + '. Previous registered version retained.';
    } catch(error) {
      if (output) output.textContent = errorText(error);
    } finally { b.disabled = false; }
    return true;
  }
  if (b.dataset.restoredActivate !== undefined) {
    const passphrase = await askEncryptedBackupPassphrase('create');
    if (passphrase == null) return true;
    const output = $('backup-result');
    b.disabled = true;
    if (output) output.textContent = 'Verifying isolated case files and preparing a recoverable activation...';
    try {
      const result = await hmr.activateRestored(passphrase);
      if (output) output.textContent = result.cancelled
        ? 'Activation cancelled; live patient files are unchanged'
        : 'Verified recovered data activated, previous database retained. HMR Desk is restarting.';
    } catch(error) {
      if (output) output.textContent = errorText(error);
      b.disabled = false;
    }
    return true;
  }
  if (b.dataset.restoredRollback !== undefined) {
    const output = $('backup-result');
    b.disabled = true;
    try {
      const result = await hmr.rollbackLastActivation();
      if (output) output.textContent = result.cancelled ? 'Rollback cancelled; nothing changed'
        : result.restarting ? 'Previous data restored. HMR Desk is restarting.'
        : (result.reason || 'Nothing to roll back');
      if (result.restarting) return true;
    } catch(error) {
      if (output) output.textContent = errorText(error);
    }
    b.disabled = false;
    return true;
  }
  if (b.dataset.workspaceMigrate !== undefined) {
    const passphrase = await askEncryptedBackupPassphrase('create');
    if (passphrase == null) return true;
    const result = $('migration-result');
    b.disabled = true;
    if (result) result.textContent = 'Verifying source, creating encrypted backup, then migrating...';
    try {
      const outcome = await hmr.migrateWorkspace(passphrase);
      if (result) result.textContent = outcome.cancelled ? 'Migration cancelled; current workspace is unchanged'
        : 'Verified migration complete. HMR Desk is restarting with the new workspace.';
    } catch (error) {
      if (result) result.textContent = errorText(error);
      b.disabled = false;
    }
    return true;
  }
  if (b.dataset.storage) {
    const output = $('storage-result');
    if (b.dataset.storage === 'rotate' && !confirm('Make a new database key? The old recovery key will stop working and a new one will be shown.')) return true;
    b.disabled = true;
    try {
      const result = await hmr.storage(b.dataset.storage);
      if (output) output.textContent = result.recovery_key
        ? 'Recovery key (write it down, then press "I have stored the recovery key"): ' + result.recovery_key
        : 'Recovery key confirmed. It cannot be shown again; make a new one if you lose it.';
    } catch (error) {
      if (output) output.textContent = errorText(error);
    } finally {
      b.disabled = false;
    }
    return true;
  }
  if (b.dataset.recordsRefresh !== undefined || b.dataset.recordsExport !== undefined || b.dataset.recordsRetire !== undefined) {
    const output = $('records-result'); const pick = $('records-patient');
    b.disabled = true;
    try {
      if (b.dataset.recordsRetire !== undefined) {
        const result = await hmr.retireRecordCopies();
        await recordsCardLoad();
        if (output) output.textContent = result.cancelled ? 'Removal cancelled' : result.removed +
          ' verified plain copies removed. ' + result.different_or_missing + ' different or unstored files, ' +
          result.skipped + ' skipped files and ' + result.errors + ' errors remain. This was not secure erasure. ' +
          'Word, PDF, source/import documents and other copies are unchanged. Windows verification is still required.';
      } else if (b.dataset.recordsRefresh !== undefined) {
        await recordsCardLoad();
      } else {
        const id = pick && pick.value !== '' ? Number(pick.value) : NaN;
        if (!Number.isInteger(id) || id < 0) { if (output) output.textContent = 'Check record storage first, then choose a patient.'; }
        else {
          const result = await hmr.exportRecords(id);
          if (output) output.textContent = result.cancelled ? 'Export cancelled' : Object.values(result.files).filter(v => v === 'written').length +
            ' files written (' + Object.values(result.files).filter(v => v === 'exists').length + ' existing files left unchanged) to ' + result.folder + '. This copy is outside the encryption HMR Desk applies; keep it somewhere you trust. MIMS files stay under your MIMS licence.';
        }
      }
    } catch (error) { if (output) output.textContent = errorText(error); }
    finally { b.disabled = false; }
    return true;
  }
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
        ? 'Backup completed and encrypted' : action === 'preview'
          ? 'Verified backup: ' + result.patients + ' patients, ' + result.workspace_files +
            ' workspace files, ' + result.bytes_uncompressed + ' bytes. No live files changed.'
          : 'Backup verified and restored into: ' + result.destination;
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
