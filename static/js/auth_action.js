// Handler for the links in Firebase Authentication emails (/auth/action).
//
// Firebase's email templates point here ("customize action URL" in the
// console). The link carries ?mode=...&oobCode=...&apiKey=...; this page uses
// its own firebaseConfig key and ignores the apiKey in the link.

firebase.initializeApp(firebaseConfig);
const auth = firebase.auth();

const RESEND_COOLDOWN_SECONDS = 60;
const STORED_AUTH_KEYS = ['auth_id_token', 'auth_refresh_token', 'auth_user_email'];

const params = new URLSearchParams(window.location.search);
const mode = params.get('mode');
const oobCode = params.get('oobCode');

let accountEmail = '';

function showPanel(name, subtitle) {
  document.querySelectorAll('.panel').forEach(function (panel) {
    panel.classList.toggle('active', panel.id === 'panel-' + name);
  });
  if (subtitle) document.getElementById('page-subtitle').textContent = subtitle;
}

function showMessage(id, text) {
  const element = document.getElementById(id);
  element.textContent = text;
  element.style.display = text ? 'block' : 'none';
}

// Firebase 10.0.0 predates password policies, so a policy rejection can arrive
// under a generic code with the server's reason in the message.
function isPasswordRuleError(error) {
  return error.code === 'auth/weak-password' ||
    error.code === 'auth/password-does-not-meet-requirements' ||
    /PASSWORD_DOES_NOT_MEET_REQUIREMENTS|WEAK_PASSWORD/.test(error.message || '');
}

function isDeadLinkError(error) {
  return ['auth/expired-action-code', 'auth/invalid-action-code',
          'auth/user-disabled', 'auth/user-not-found'].indexOf(error.code) !== -1;
}

// Plain-language reason a link could not be used.
function describeLinkError(error) {
  switch (error.code) {
    case 'auth/expired-action-code':
      return 'This link has expired.';
    case 'auth/invalid-action-code':
      return 'This link is no longer valid. It was already used, or a newer email replaced it. ' +
        'If you asked for more than one email, use the most recent one.';
    case 'auth/user-disabled':
      return 'This account has been disabled. Please contact the VoucherVision team.';
    case 'auth/user-not-found':
      return 'The account for this link no longer exists.';
    case 'auth/network-request-failed':
      return 'We could not reach the sign-in service. Check your connection and reload this page.';
    default:
      return 'We could not check this link (' + (error.code || 'unknown error') + '). Reload the page to try again.';
  }
}

function showFailure(message, options) {
  options = options || {};
  showMessage('failure-message', message);
  document.getElementById('resend').style.display = options.allowResend === false ? 'none' : 'block';
  if (accountEmail) document.getElementById('resend-email').value = accountEmail;
  showPanel('failure', options.subtitle || 'This link cannot be used');
}

// ----- Password reset -----

function startPasswordReset() {
  auth.verifyPasswordResetCode(oobCode)
    .then(function (email) {
      accountEmail = email;
      document.getElementById('account-email').textContent = email;
      PasswordPolicy.render(document.getElementById('password-rules'), '');
      showPanel('reset', 'Reset your password');
      document.getElementById('new-password').focus();
    })
    .catch(function (error) {
      showFailure(describeLinkError(error), {
        allowResend: error.code !== 'auth/user-disabled' && error.code !== 'auth/network-request-failed'
      });
    });
}

async function submitNewPassword() {
  const password = document.getElementById('new-password').value;
  const confirmation = document.getElementById('confirm-password').value;
  const button = document.getElementById('reset-button');
  showMessage('reset-error', '');

  const missing = PasswordPolicy.missing(password);
  if (missing.length) {
    showMessage('reset-error', 'Password needs ' + missing.join(', ') + '.');
    return;
  }
  if (password !== confirmation) {
    showMessage('reset-error', 'Passwords do not match.');
    return;
  }

  button.disabled = true;
  button.textContent = 'Saving...';
  try {
    await auth.confirmPasswordReset(oobCode, password);
  } catch (error) {
    button.disabled = false;
    button.textContent = 'Set New Password';
    if (isPasswordRuleError(error)) {
      showMessage('reset-error', 'That password does not meet the requirements listed above.');
    } else if (isDeadLinkError(error)) {
      showFailure(describeLinkError(error), { allowResend: error.code !== 'auth/user-disabled' });
    } else {
      showMessage('reset-error', describeLinkError(error));
    }
    return;
  }

  // The password is changed. Any session this browser still holds was revoked
  // by the reset, so drop it before signing in with the new password.
  showPanel('loading', 'Password updated, signing you in...');
  try { await auth.signOut(); } catch (error) { /* nothing to sign out of */ }
  STORED_AUTH_KEYS.forEach(function (key) { localStorage.removeItem(key); });

  try {
    const credential = await auth.signInWithEmailAndPassword(accountEmail, password);
    window.location.href = await destinationFor(credential.user);
  } catch (error) {
    // Includes accounts that need a second sign-in step.
    console.warn('Automatic sign-in after reset did not complete:', error);
    showMessage('done-message', 'Your password has been updated. Please sign in with your new password.');
    showPanel('done', 'Password updated');
  }
}

// Same routing the login page does after a successful sign-in.
async function destinationFor(user) {
  const idToken = await user.getIdToken();
  const response = await fetch('/check-approval-status', {
    headers: { 'Authorization': 'Bearer ' + idToken }
  });
  if (!response.ok) throw new Error('Approval check failed with status ' + response.status);
  const data = await response.json();

  if (data.status === 'approved') {
    localStorage.setItem('auth_user_email', user.email);
    localStorage.setItem('auth_id_token', idToken);
    if (user.refreshToken) localStorage.setItem('auth_refresh_token', user.refreshToken);
    return '/auth-success';
  }
  if (data.status === 'pending') return '/pending-approval';
  if (data.status === 'rejected') return '/application-rejected';
  throw new Error('Unknown approval status: ' + data.status);
}

// ----- Email verification -----

function startEmailVerification() {
  auth.applyActionCode(oobCode)
    .then(function () {
      showMessage('done-message', 'Your email address has been verified.');
      showPanel('done', 'Email verified');
    })
    .catch(function (error) {
      showFailure(describeLinkError(error), { allowResend: false });
    });
}

// ----- "Send me a new link" -----

function startResendCooldown(button) {
  let remaining = RESEND_COOLDOWN_SECONDS;
  button.disabled = true;
  const timer = setInterval(function () {
    remaining -= 1;
    if (remaining <= 0) {
      clearInterval(timer);
      button.disabled = false;
      button.textContent = 'Send Me a New Link';
    } else {
      button.textContent = 'Send again in ' + remaining + 's';
    }
  }, 1000);
  button.textContent = 'Send again in ' + remaining + 's';
}

function resendResetLink() {
  const email = document.getElementById('resend-email').value.trim();
  const button = document.getElementById('resend-button');
  showMessage('resend-error', '');
  showMessage('resend-success', '');
  if (!email) {
    showMessage('resend-error', 'Please enter your email address.');
    return;
  }
  button.disabled = true;
  auth.sendPasswordResetEmail(email)
    .then(function () {
      showMessage('resend-success', 'If an account exists for ' + email +
        ', a new reset email is on its way. Use the most recent email, and check your spam folder.');
      startResendCooldown(button);
    })
    .catch(function (error) {
      button.disabled = false;
      showMessage('resend-error', error.code === 'auth/invalid-email'
        ? 'That does not look like a valid email address.'
        : 'Could not send the email (' + (error.code || 'unknown error') + '). Please try again.');
    });
}

// ----- Start -----

document.getElementById('reset-button').addEventListener('click', submitNewPassword);
document.getElementById('resend-button').addEventListener('click', resendResetLink);
document.getElementById('new-password').addEventListener('input', function (event) {
  PasswordPolicy.render(document.getElementById('password-rules'), event.target.value);
});
['new-password', 'confirm-password'].forEach(function (id) {
  document.getElementById(id).addEventListener('keydown', function (event) {
    if (event.key === 'Enter') submitNewPassword();
  });
});

(function start() {
  if (mode && oobCode && mode !== 'resetPassword' && mode !== 'verifyEmail') {
    // Email types this page does not handle itself (for example, undoing an
    // email change) go to Firebase's own page, with this page's working key.
    params.set('apiKey', firebaseConfig.apiKey);
    window.location.replace('https://' + firebaseConfig.authDomain + '/__/auth/action?' + params.toString());
    return;
  }

  // Keep the one-time code out of the address bar and browser history.
  window.history.replaceState(null, '', window.location.pathname);

  if (!mode || !oobCode) {
    showFailure('This link is incomplete. Open the link from your email again, or request a new one below.');
    return;
  }

  if (mode === 'verifyEmail') {
    startEmailVerification();
    return;
  }

  PasswordPolicy.load(firebaseConfig.apiKey).then(startPasswordReset);
})();
