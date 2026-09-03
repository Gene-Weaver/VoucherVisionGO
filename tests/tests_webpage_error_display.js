// The web UI must surface the server's structured error, not just the status.
//
// Run from the repository root:  node tests/tests_webpage_error_display.js
const fs = require('fs');
const path = require('path');

const ROOT = path.dirname(__dirname);
const src = fs.readFileSync(path.join(ROOT, 'webpage/js/vouchervisiongo.js'), 'utf8');
const batch = fs.readFileSync(path.join(ROOT, 'webpage/js/batch_processing.js'), 'utf8');
const indexHtml = fs.readFileSync(path.join(ROOT, 'webpage/index.html'), 'utf8');

let fails = 0;
function check(label, cond, detail = '') {
  if (!cond) fails++;
  console.log(`${cond ? 'PASS' : 'FAIL'}  ${label.padEnd(58)} ${detail}`);
}

// Load describeApiError out of the real source, without the browser globals.
const start = src.indexOf('async function describeApiError');
const end = src.indexOf('\n}', start) + 2;
check('describeApiError is defined in vouchervisiongo.js', start !== -1);
const describeApiError = eval(`(${src.slice(start, end).replace(/^async function describeApiError/, 'async function')})`);

function fakeResponse(body, { status = 500, statusText = 'Internal Server Error', rid = null } = {}) {
  return {
    status, statusText,
    headers: { get: (k) => (k.toLowerCase() === 'x-request-id' ? rid : null) },
    text: async () => (typeof body === 'string' ? body : JSON.stringify(body)),
  };
}

(async () => {
  console.log('=== the sanitized server message reaches the user ===');
  let msg = await describeApiError(fakeResponse({
    error: 'The image could not be retrieved from the supplied URL.',
    error_code: 'FETCH_FAILED', host: 'VoucherVisionGO', request_id: 'rid-1',
  }, { status: 502, statusText: 'Bad Gateway' }));
  check('shows the server error text', msg.includes('could not be retrieved'), msg);
  check('includes the error_code', msg.includes('FETCH_FAILED'), msg);
  check('includes the request id', msg.includes('rid-1'), msg);
  check('is not just the HTTP status', msg !== 'API error: 502 Bad Gateway');

  msg = await describeApiError(fakeResponse({
    error: 'Rate limit exceeded',
    message: 'You have used all 100 of your Gemini Pro requests.',
    error_code: 'QUOTA_EXHAUSTED',
  }, { status: 503 }));
  check('shows error and message when both are present',
        msg.includes('Rate limit exceeded') && msg.includes('all 100'), msg);

  msg = await describeApiError(fakeResponse({
    error: 'The supplied image URL is not a valid URL.', error_code: 'URL_INVALID',
  }, { status: 400 }));
  check('a 400 URL_INVALID is explained, not shown as a generic failure',
        msg.includes('not a valid URL'), msg);

  console.log('\n=== degrades safely ===');
  msg = await describeApiError(fakeResponse('<html>502 Bad Gateway</html>',
                                            { status: 502, rid: 'rid-2' }));
  check('non-JSON body falls back to the status', msg.includes('502'), msg);
  check('...and still surfaces the request id header', msg.includes('rid-2'), msg);

  console.log('\n=== remote content cannot become markup ===');
  // The message is rendered into the DOM, so an attacker-influenced upstream
  // body must never reach it, and must never be interpreted as HTML.
  const XSS = '<img src=x onerror="window.__pwned=1">';
  msg = await describeApiError(fakeResponse(XSS, { status: 502 }));
  check('raw non-JSON body is NOT echoed into the message', !msg.includes('<img'), msg);
  check('no onerror handler survives', !msg.includes('onerror'), msg);
  const vvSrc = fs.readFileSync(path.join(ROOT, 'webpage/js/vouchervisiongo.js'), 'utf8');
  check('raw remote body is not logged to the console either',
        !/console\.(debug|log|warn|error)\([^)]*\braw\b/.test(vvSrc));
  // A server-supplied message is trusted-ish but still rendered as text.
  msg = await describeApiError(fakeResponse({ error: XSS, error_code: 'X' }, { status: 500 }));
  check('a JSON error field is passed through verbatim (escaped at render)',
        msg.includes(XSS), 'renderer must escape');
  const vv = fs.readFileSync(path.join(ROOT, 'webpage/js/vouchervisiongo.js'), 'utf8');
  check('error is rendered with .text(), not interpolated into .html()',
        !/\$\('#singleResults'\)\.html\(`[\s\S]*?\$\{errorMsg\}/.test(vv));
  check('...via a text() call on the error paragraph',
        /\.append\(\$\('<p>'\)\.text\(errorMsg\)\)/.test(vv));
  msg = await describeApiError(fakeResponse('', { status: 500 }));
  check('empty body still yields a message', msg.length > 0, msg);
  const bomb = { status: 500, statusText: 'x', headers: { get: () => null },
                 text: async () => { throw new Error('stream error'); } };
  msg = await describeApiError(bomb);
  check('unreadable body does not throw', typeof msg === 'string', msg);

  console.log('\n=== both call sites use it ===');
  check('vouchervisiongo.js no longer discards errorText', !src.includes('const errorText = await response.text();'));
  check('vouchervisiongo.js uses describeApiError', src.includes('await describeApiError(response)'));
  const bare = (batch.match(/throw new Error\(`API error: \$\{response\.status\} \$\{response\.statusText\}`\);/g) || []);
  check('batch_processing.js has no bare status-only throw left', bare.length === 0, `${bare.length} left`);
  check('batch_processing.js calls describeApiError',
        (batch.match(/describeApiError\(response\)/g) || []).length === 2,
        `${(batch.match(/describeApiError\(response\)/g) || []).length} sites`);
  check('vouchervisiongo.js loads before batch_processing.js',
        indexHtml.indexOf('js/vouchervisiongo.js') < indexHtml.indexOf('js/batch_processing.js'));

  console.log(`\n${fails ? fails + ' FAILED' : 'ALL PASS'}`);
  process.exit(fails ? 1 : 0);
})();
