// Adds a show/hide button and a copy button to every password field on the
// page. Include this script after the form markup; no other setup is needed.
// "Confirm" fields get the show/hide button only.
(function () {
  const ICONS = {
    show: '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7S1 12 1 12z"/><circle cx="12" cy="12" r="3"/></svg>',
    hide: '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M17.94 17.94A10.9 10.9 0 0 1 12 19c-7 0-11-7-11-7a19.6 19.6 0 0 1 5.06-5.94"/><path d="M9.9 4.24A10.4 10.4 0 0 1 12 4c7 0 11 8 11 8a19.7 19.7 0 0 1-3.17 4.19"/><path d="M14.12 14.12a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/></svg>',
    copy: '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>',
    done: '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="20 6 9 17 4 12"/></svg>'
  };

  const CSS = [
    '.password-tools { display: flex; gap: 6px; align-items: stretch; }',
    '.password-tools > input { flex: 1 1 auto; min-width: 0; }',
    '.password-tool { flex: 0 0 auto; width: 40px; display: inline-flex; align-items: center; justify-content: center;',
    '  padding: 0; border: 1px solid #ddd; border-radius: 4px; background: #fff; color: #555; cursor: pointer; }',
    '.password-tool:hover { background: #f1f3f4; color: #222; }',
    '.password-tool:focus-visible { outline: 2px solid #4285f4; outline-offset: 1px; }',
    '.password-tool.copied { color: #28a745; border-color: #28a745; }',
    'body.dark-mode .password-tool { background: #1a1a1a; border-color: #333; color: #bbb; }',
    'body.dark-mode .password-tool:hover { background: #2a2a2a; color: #eee; }',
    'body.dark-mode .password-tool.copied { color: #66BB6A; border-color: #66BB6A; }'
  ].join('\n');

  function makeButton(icon, label) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'password-tool';
    button.innerHTML = ICONS[icon];
    button.title = label;
    button.setAttribute('aria-label', label);
    return button;
  }

  function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) {
      return navigator.clipboard.writeText(text);
    }
    // Fallback for browsers or frames where the Clipboard API is unavailable.
    return new Promise(function (resolve, reject) {
      const area = document.createElement('textarea');
      area.value = text;
      area.style.position = 'fixed';
      area.style.opacity = '0';
      document.body.appendChild(area);
      area.select();
      let ok = false;
      try { ok = document.execCommand('copy'); } catch (error) { /* blocked */ }
      document.body.removeChild(area);
      if (ok) { resolve(); } else { reject(new Error('Copy was blocked by the browser')); }
    });
  }

  function enhance(input) {
    if (input.dataset.passwordTools) return;
    input.dataset.passwordTools = 'on';

    const wrapper = document.createElement('div');
    wrapper.className = 'password-tools';
    input.parentNode.insertBefore(wrapper, input);
    wrapper.appendChild(input);

    const toggle = makeButton('show', 'Show password');
    toggle.addEventListener('click', function () {
      const reveal = input.type === 'password';
      input.type = reveal ? 'text' : 'password';
      const label = reveal ? 'Hide password' : 'Show password';
      toggle.innerHTML = ICONS[reveal ? 'hide' : 'show'];
      toggle.title = label;
      toggle.setAttribute('aria-label', label);
    });
    wrapper.appendChild(toggle);

    if (/confirm/i.test(input.id)) return;

    const copy = makeButton('copy', 'Copy password');
    let resetTimer;
    copy.addEventListener('click', function () {
      if (!input.value) return;
      copyText(input.value).then(function () {
        copy.innerHTML = ICONS.done;
        copy.classList.add('copied');
        copy.title = 'Copied';
        clearTimeout(resetTimer);
        resetTimer = setTimeout(function () {
          copy.innerHTML = ICONS.copy;
          copy.classList.remove('copied');
          copy.title = 'Copy password';
        }, 1500);
      }).catch(function (error) {
        console.warn('Could not copy the password:', error);
        copy.title = 'Copy was blocked by the browser';
      });
    });
    wrapper.appendChild(copy);
  }

  const style = document.createElement('style');
  style.textContent = CSS;
  document.head.appendChild(style);
  document.querySelectorAll('input[type="password"]').forEach(enhance);
})();
