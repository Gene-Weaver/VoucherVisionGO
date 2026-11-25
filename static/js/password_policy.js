// Shared password rules for the signup page and the reset page (/auth/action).
//
// The rules live in Firebase (Authentication > Settings > Password policy).
// load() reads the live policy so a console change is picked up without a
// deploy; DEFAULT_POLICY is the fallback when that request fails.
(function (root) {
  const DEFAULT_POLICY = {
    minLength: 24,
    maxLength: 4096,
    lower: true,
    upper: true,
    number: true,
    symbol: true,
    symbols: '^$*.[]{}()?"!@#%&/\\,><\':;|_~`-'
  };

  let policy = Object.assign({}, DEFAULT_POLICY);

  // Convert Firebase's passwordPolicy response into our shape.
  function fromFirebase(json) {
    const opts = (json && json.customStrengthOptions) || {};
    const enforced = json && json.enforcementState === 'ENFORCE';
    const symbols = Array.isArray(json && json.allowedNonAlphanumericCharacters)
      ? json.allowedNonAlphanumericCharacters.join('')
      : DEFAULT_POLICY.symbols;
    if (!enforced) {
      // Policy switched off: only Firebase's built-in 6-character minimum applies.
      return { minLength: 6, maxLength: 4096, lower: false, upper: false, number: false, symbol: false, symbols: symbols };
    }
    return {
      minLength: opts.minPasswordLength || 6,
      maxLength: opts.maxPasswordLength || 4096,
      lower: !!opts.containsLowercaseCharacter,
      upper: !!opts.containsUppercaseCharacter,
      number: !!opts.containsNumericCharacter,
      symbol: !!opts.containsNonAlphanumericCharacter,
      symbols: symbols
    };
  }

  // Read the live policy. Never rejects: on any failure the fallback stays.
  async function load(apiKey) {
    try {
      const response = await fetch(
        'https://identitytoolkit.googleapis.com/v2/passwordPolicy?key=' + encodeURIComponent(apiKey)
      );
      if (response.ok) {
        policy = fromFirebase(await response.json());
      }
    } catch (error) {
      console.warn('Could not load the password policy, using built-in rules:', error);
    }
    return policy;
  }

  function hasSymbol(password) {
    for (const ch of password) {
      if (policy.symbols.indexOf(ch) !== -1) return true;
    }
    return false;
  }

  // Every active rule with whether the password meets it.
  function check(password) {
    password = password || '';
    const rules = [{ label: 'at least ' + policy.minLength + ' characters', ok: password.length >= policy.minLength }];
    if (password.length > policy.maxLength) {
      rules.push({ label: 'no more than ' + policy.maxLength + ' characters', ok: false });
    }
    if (policy.lower) rules.push({ label: 'a lowercase letter', ok: /[a-z]/.test(password) });
    if (policy.upper) rules.push({ label: 'an uppercase letter', ok: /[A-Z]/.test(password) });
    if (policy.number) rules.push({ label: 'a number', ok: /[0-9]/.test(password) });
    if (policy.symbol) rules.push({ label: 'a special character', ok: hasSymbol(password) });
    return rules;
  }

  // Labels of the rules the password does not meet (empty when it passes).
  function missing(password) {
    return check(password).filter(function (rule) { return !rule.ok; }).map(function (rule) { return rule.label; });
  }

  // Draw the rules as a checklist inside a <ul>.
  function render(listElement, password) {
    if (!listElement) return;
    listElement.replaceChildren();
    check(password).forEach(function (rule) {
      const item = document.createElement('li');
      item.className = rule.ok ? 'password-rule met' : 'password-rule';
      item.textContent = (rule.ok ? '✓ ' : '• ') + rule.label;
      listElement.appendChild(item);
    });
  }

  const api = { load: load, check: check, missing: missing, render: render, _fromFirebase: fromFirebase,
                _set: function (p) { policy = p; } };
  root.PasswordPolicy = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
