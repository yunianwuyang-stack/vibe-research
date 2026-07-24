'use strict';

// Generated Express projects commonly call app.listen(PORT), which makes Node
// listen on every interface.  Preview processes must remain loopback-only even
// when the generated application does not consume the HOST environment value.
const net = require('node:net');
const marker = Symbol.for('vibeResearch.previewLoopbackGuard');
const originalListen = net.Server.prototype.listen;

if (!originalListen[marker]) {
  function loopbackListen(...args) {
    const first = args[0];
    if (typeof first === 'number' || (typeof first === 'string' && /^\d+$/.test(first))) {
      args[0] = Number(first);
      if (typeof args[1] === 'string') {
        args[1] = '127.0.0.1';
      } else {
        args.splice(1, 0, '127.0.0.1');
      }
    } else if (first && typeof first === 'object' && Object.prototype.hasOwnProperty.call(first, 'port')) {
      args[0] = { ...first, host: '127.0.0.1' };
    }
    return originalListen.apply(this, args);
  }

  Object.defineProperty(loopbackListen, marker, { value: true });
  net.Server.prototype.listen = loopbackListen;
}
