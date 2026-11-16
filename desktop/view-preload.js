const VERIFIED_PRODA_OTP_PATH = '/mga/sps/authsvc/policy/proda';
const OTP_PHRASE = /verification[-_\s]*code|one[-_\s]*time[-_\s]*code|security[-_\s]*code|sms[-_\s]*code|verification[-_\s]*token|enter\s*(?:sms\s*)?code/i;

const visible = (el) => !el.disabled && !!el.getClientRects().length && getComputedStyle(el).visibility !== 'hidden';

function postSelfAction(doc, form, button) {
  try {
    const actionOwner = button.hasAttribute('formaction') ? button : form;
    const actionAttr = actionOwner === button ? 'formaction' : 'action';
    if (actionOwner.hasAttribute(actionAttr) && !actionOwner.getAttribute(actionAttr).trim()) return null;
    const action = actionOwner === button ? button.formAction : form.action;
    const method = button.hasAttribute('formmethod') ? button.formMethod : form.method;
    const target = button.hasAttribute('formtarget') ? button.formTarget : form.target || doc.querySelector('base[target]')?.target || '_self';
    const url = new URL(action);
    return /^post$/i.test(method) && /^_self$/i.test(target) ? url : null;
  } catch { return null; }
}

function loginFields(doc) {
  const inputs = [...doc.querySelectorAll('input')].filter(visible);
  const passwords = inputs.filter((el) => el.type === 'password');
  const otp = inputs.some(
    (el) =>
      /one-time-code/i.test(el.autocomplete || '') ||
      OTP_PHRASE.test([el.placeholder, el.getAttribute?.('aria-label') || ''].join(' ')) ||
      /otp|code|token|2fa|verification/i.test(
        [el.name, el.id, ...(el.labels ? [...el.labels].map((l) => l.textContent) : [])].join(' '),
      ),
  );
  if (passwords.length !== 1 || otp) return null;
  const password = passwords[0];
  if (!password.form) return null;
  const before = [...password.form.querySelectorAll('input')];
  const username = before
    .slice(0, before.indexOf(password))
    .filter((el) => visible(el) && ['text', 'email'].includes(el.type))
    .pop();
  return username ? { username, password, form: password.form } : null;
}

function prodaLoginSubmitter(doc, fields) {
  if (!fields || doc.location.origin !== 'https://proda.humanservices.gov.au') return null;
  const buttons = [...fields.form.querySelectorAll('button[type=submit], input[type=submit], button:not([type])')].filter(visible);
  if (buttons.length !== 1) return null;
  const button = buttons[0];
  if (button.form !== fields.form) return null;
  const label = (button.tagName === 'INPUT' ? button.value : button.textContent || '').trim();
  if (!/^(?:login|log\s+in|sign\s+in|continue|next)$/i.test(label)) return null;
  const url = postSelfAction(doc, fields.form, button);
  if (!url || url.origin !== 'https://proda.humanservices.gov.au' || url.username || url.password) return null;
  return button;
}

function otpCandidates(doc) {
  const inputs = [...doc.querySelectorAll('input')].filter(visible);
  const otps = inputs.filter((el) => {
    if (['hidden', 'submit', 'button', 'checkbox', 'radio', 'file'].includes(el.type)) return false;
    if (/one-time-code/i.test(el.autocomplete || '')) return true;
    const labelText = el.labels ? [...el.labels].map((l) => l.textContent).join(' ') : '';
    const text = [el.name, el.id, el.placeholder, el.getAttribute('aria-label') || '', labelText].join(' ');
    return (
      OTP_PHRASE.test(text)
    );
  });
  if (inputs.some(el => el.type === 'password' && !otps.includes(el))) return [];
  if (otps.some(el => el.type === 'password') && inputs.some(el => ['text', 'email'].includes(el.type) && !otps.includes(el))) return [];
  if (inputs.some(el => ['text', 'email'].includes(el.type) && [el.name, el.id, el.autocomplete].some(value => /^(?:username|user[-_]?name|user[-_]?id|login|email)$/i.test(value || '')))) return [];
  return otps;
}

function otpFields(doc) {
  // The real Next button starts disabled and must still be detected.
  const visible = (el) => !!el.getClientRects().length && getComputedStyle(el).visibility !== 'hidden';
  const candidates = otpCandidates(doc);
  if (candidates.length !== 1) return null;
  const otpInput = candidates[0];
  const form = otpInput.form;
  if (!form) return null;
  const buttons = [...form.querySelectorAll('button[type=submit], input[type=submit], button:not([type])')].filter(visible);
  if (buttons.length !== 1) return null;
  const submitBtn = buttons[0];
  if (submitBtn.form !== form) return null;
  const label = (submitBtn.innerText || submitBtn.value || submitBtn.textContent || '').trim();
  const actionWords = [label, submitBtn.name, submitBtn.value, submitBtn.id, form.id, form.name].join(' ');
  if (/resend|re-send|send\s+again|refresh|retry|another|new\s+code|cancel|back/i.test(actionWords)) return null;
  const hiddenActions = [...form.querySelectorAll('input[type=hidden]')].filter(input => /action|event|operation/i.test(input.name || ''));
  if (hiddenActions.some(input => input.value && !/^(?:verify|confirm|continue|next|submit|login|sign.?in)$/i.test(input.value))) return null;
  if (!/^(?:next|verify(?:\s+(?:code|identity))?|confirm(?:\s+(?:code|identity))?|submit(?:\s+code)?|sign\s+in|log\s+in)$/i.test(label)) return null;
  try {
    const url = postSelfAction(doc, form, submitBtn);
    if (!url) return null;
    const keys = [...url.searchParams.keys()], states = url.searchParams.getAll('StateId'), operations = url.searchParams.getAll('operation');
    if (url.origin !== 'https://proda.humanservices.gov.au' || url.username || url.password || url.hash || url.pathname !== VERIFIED_PRODA_OTP_PATH ||
        keys.length !== 2 || states.length !== 1 || operations.length !== 1 || operations[0] !== 'verify' || !/^[A-Za-z0-9._~-]{1,256}$/.test(states[0])) return null;
    return { input: otpInput, form, submitBtn, action: url.href };
  } catch { return null; }
}

async function submitOtp(doc, otp, code, stillCurrent) {
  const unchanged = () => {
    const current = otpFields(doc);
    return stillCurrent() && current && current.input === otp.input && current.form === otp.form && current.submitBtn === otp.submitBtn && current.action === otp.action;
  };
  if (!unchanged() || otp.input.value !== '' || typeof code !== 'string' || !/^\d{6}$/.test(code) || typeof otp.form.requestSubmit !== 'function') return false;
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
  setter.call(otp.input, code);
  otp.input.dispatchEvent(new Event('input', { bubbles: true }));
  otp.input.dispatchEvent(new Event('change', { bubbles: true }));
  const deadline = Date.now() + 1000;
  while (otp.submitBtn.disabled && Date.now() < deadline) {
    if (!unchanged() || otp.input.value !== code) return false;
    await new Promise(resolve => setTimeout(resolve, 50));
  }
  if (!unchanged() || otp.input.value !== code || otp.submitBtn.disabled) return false;
  let observed;
  const onSubmit = event => { if (event.target === otp.form && event.submitter === otp.submitBtn) observed = event; };
  otp.form.addEventListener('submit', onSubmit, true);
  try { otp.form.requestSubmit(otp.submitBtn); } catch { return false; }
  finally { otp.form.removeEventListener('submit', onSubmit, true); }
  return observed && !observed.defaultPrevented ? true : null;
}

if (typeof module !== 'undefined' && module.exports) module.exports = { loginFields, otpFields, submitOtp };

if (typeof process !== 'undefined' && process.type === 'renderer') {
  const { contextBridge, ipcRenderer } = require('electron');
  contextBridge.exposeInMainWorld('hmrBridge', {
    sendMessage: (message) => ipcRenderer.invoke('save-helper', message),
  });
  if (window === window.top) {
    let filled = false;
    let lastStatus = '';
    let passwordElement = null;
    let lastOtpStatus = '';
    let prodaSubmitting = false;
    let otpFilled = false;
    let otpElement = null;
    let otpAction = null;
    let otpNonce = null;
    let otpManual = false;
    let unsafeOtpElement = null;
    const beforeSubmit = async () => {
      let timer;
      try {
        await Promise.race([ipcRenderer.invoke('proda-before-submit'), new Promise(resolve => { timer = setTimeout(() => { ipcRenderer.send('proda-start-cancel'); resolve(); }, 4000); })]);
      } finally { clearTimeout(timer); }
    };

    const reportOtp = () => {
      if (location.origin !== 'https://proda.humanservices.gov.au') return;
      const otp = otpFields(document);
      const unsafe = otp ? null : otpCandidates(document)[0] || null;
      if (unsafe && unsafe !== unsafeOtpElement) ipcRenderer.send('proda-otp-manual');
      unsafeOtpElement = unsafe;
      if ((otp?.input || null) !== otpElement || (otp?.action || null) !== otpAction) {
        otpElement = otp?.input || null;
        otpAction = otp?.action || null;
        otpNonce = otp ? crypto.randomUUID() : null;
        otpFilled = false;
        otpManual = false;
      }
      if (otp && otp.input.value !== '' && !otpManual && !otpFilled) {
        otpManual = true;
        ipcRenderer.send('proda-otp-manual');
      }
      const status = String(!!otp && !otpManual) + (otpNonce || '');
      if (status !== lastOtpStatus) {
        lastOtpStatus = status;
        ipcRenderer.send('proda-otp-page', !!otp && !otpManual, otpNonce);
      }
      if (otp && !otp.input.__manualHooked) {
        otp.input.__manualHooked = true;
        otp.input.addEventListener('input', (e) => {
          if (e.isTrusted) { otpManual = true; ipcRenderer.send('proda-otp-manual'); }
        });
      }
    };

    const report = () => {
      const fields = loginFields(document);
      const status = String(!!fields);
      if (status !== lastStatus) {
        lastStatus = status;
        ipcRenderer.send('sign-in-page', !!fields);
      }
      if ((fields?.password || null) !== passwordElement) {
        passwordElement = fields?.password || null;
        if (fields && location.origin === 'https://proda.humanservices.gov.au') ipcRenderer.send('proda-password-page');
      }
      if (fields && !fields.form.__prodaHooked && location.origin === 'https://proda.humanservices.gov.au') {
        fields.form.__prodaHooked = true;
        fields.form.addEventListener(
          'submit',
          async (e) => {
            if (prodaSubmitting) return;
            e.preventDefault();
            e.stopImmediatePropagation();
            prodaSubmitting = true;
            try {
              await beforeSubmit();
            } catch {}
            const current = loginFields(document);
            if (location.origin !== 'https://proda.humanservices.gov.au' || !current || current.form !== fields.form || current.password !== fields.password) { prodaSubmitting = false; return; }
            ipcRenderer.send('sign-in-submitted');
            try {
              if (typeof fields.form.requestSubmit === 'function') {
                fields.form.requestSubmit(e.submitter || undefined);
              } else {
                HTMLFormElement.prototype.submit.call(fields.form);
              }
            } catch {
              try {
                HTMLFormElement.prototype.submit.call(fields.form);
              } catch {}
            } finally { prodaSubmitting = false; }
          },
          { capture: true },
        );
      }
      reportOtp();
    };

    ipcRenderer.on('sign-in-detect', () => {
      filled = false;
      ipcRenderer.send('sign-in-page', !!loginFields(document));
    });

    ipcRenderer.on('sign-in-read', () => {
      const fields = loginFields(document);
      if (fields)
        ipcRenderer.send('sign-in-save', { username: fields.username.value, password: fields.password.value });
    });

    ipcRenderer.on('sign-in-fill', async (_event, credentials) => {
      if (filled || location.protocol !== 'https:' || location.origin !== credentials.origin) return;
      const fields = loginFields(document);
      if (!fields) return;
      filled = true;
      const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
      for (const [field, value] of [
        [fields.username, credentials.username],
        [fields.password, credentials.password],
      ]) {
        setter.call(field, value);
        field.dispatchEvent(new Event('input', { bubbles: true }));
        field.dispatchEvent(new Event('change', { bubbles: true }));
      }
      if (credentials.submit) {
        let submitter = null;
        if (location.origin === 'https://proda.humanservices.gov.au') {
          submitter = prodaLoginSubmitter(document, fields);
          if (!submitter || typeof fields.form.requestSubmit !== 'function') return;
          prodaSubmitting = true;
          try {
            await beforeSubmit();
          } catch {}
        }
        const current = loginFields(document);
        if (!current || current.form !== fields.form || current.password !== fields.password || location.origin !== credentials.origin ||
            (submitter && prodaLoginSubmitter(document, current) !== submitter)) { prodaSubmitting = false; return; }
        ipcRenderer.send('sign-in-submitted');
        if (typeof fields.form.requestSubmit === 'function') {
          if (submitter) fields.form.requestSubmit(submitter);
          else fields.form.requestSubmit();
        } else {
          const btn = fields.form.querySelector('button[type=submit], input[type=submit], button:not([type])');
          if (btn) btn.click();
          else HTMLFormElement.prototype.submit.call(fields.form);
        }
        prodaSubmitting = false;
      }
    });

    ipcRenderer.on('proda-otp-fill', async (_event, data) => {
      if (location.protocol !== 'https:' || location.origin !== 'https://proda.humanservices.gov.au') return;
      const otp = otpFields(document);
      if (otpFilled || otpManual || !otp || otp.input !== otpElement || !data || data.nonce !== otpNonce || typeof data.code !== 'string' || !/^\d{6}$/.test(data.code)) {
        if (data && typeof data === 'object') data.code = null;
        ipcRenderer.send('proda-otp-rejected');
        return;
      }
      otpFilled = true;
      let accepted = false;
      try {
        accepted = await submitOtp(document, otp, data.code, () =>
          !otpManual && location.origin === 'https://proda.humanservices.gov.au' && otpNonce === data.nonce && otpAction === otp.action);
      } catch {} finally { data.code = null; }
      if (accepted === true) ipcRenderer.send('proda-otp-submitted', otpNonce);
      else if (accepted === false) ipcRenderer.send('proda-otp-rejected');
    });

    window.addEventListener('DOMContentLoaded', () => {
      report();
      new MutationObserver(report).observe(document.documentElement, {
        subtree: true,
        childList: true,
        attributes: true,
      });
    });
  }
}
