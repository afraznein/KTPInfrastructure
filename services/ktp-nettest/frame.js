// ktp-nettest frame: the website embeds GET /frame in a sandboxed iframe, so client.js runs in this
// node's origin and never in the site's. The site posts a ticket in; progress and the result come back.
(function () {
  'use strict';
  const parentOrigin = document.querySelector('meta[name="ktp-parent-origin"]').content;
  const nettest = window.KtpNettest;
  let running = false;
  const reply = (msg) => window.parent.postMessage(msg, parentOrigin);

  window.addEventListener('message', async (e) => {
    if (e.source !== window.parent || e.origin !== parentOrigin) return;
    const m = e.data;
    if (!m || m.type !== 'ktp-nettest:run' || typeof m.ticket !== 'string' || running) return;
    running = true;
    try {
      const result = await nettest.runTest({
        base: location.origin,
        ticket: m.ticket,
        onProgress: (p) => reply({ type: 'ktp-nettest:progress', phase: String(p.phase), done: Number(p.done) || 0 }),
      });
      reply({ type: 'ktp-nettest:result', result });
    } catch (err) {
      reply({
        type: 'ktp-nettest:error',
        busy: err instanceof nettest.Busy,
        message: String((err && err.message) || err).slice(0, 300),
      });
    } finally {
      running = false;
    }
  });

  reply({ type: 'ktp-nettest:ready', version: nettest.VERSION });
})();
