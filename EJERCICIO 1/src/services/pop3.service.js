const tls = require('tls');
const net = require('net');
const { pop3 } = require('../config');
const { parsear } = require('./parser');

function conectar() {
  const opts = { host: pop3.host, port: pop3.port };
  const sock = pop3.tls ? tls.connect(opts) : net.connect(opts); // sin TLS solo para pruebas locales
  sock.setEncoding('latin1'); // 1 byte = 1 caracter, se reconvierte a Buffer luego
  let buf = '';
  let pending = null;

  function check() {
    if (!pending) return;
    const { multi, resolve, reject } = pending;
    const fin = buf.indexOf('\r\n');
    if (fin === -1) return;
    const first = buf.slice(0, fin);
    if (first.startsWith('-ERR')) { pending = null; buf = ''; return reject(new Error(first)); }
    if (!multi) { pending = null; buf = buf.slice(fin + 2); return resolve(first); }
    const end = buf.indexOf('\r\n.\r\n', fin); // fin de respuesta multilínea
    if (end === -1) return;
    const body = buf.slice(fin + 2, end + 2).replace(/^\.\./gm, '.'); // des-"byte stuffing"
    pending = null;
    buf = buf.slice(end + 5);
    resolve(body);
  }

  sock.on('data', d => { buf += d; check(); });
  sock.on('error', e => pending && pending.reject(e));

  return {
    send(line, multi = false) {
      return new Promise((resolve, reject) => {
        pending = { multi, resolve, reject };
        if (line !== null) sock.write(line + '\r\n');
        check();
      });
    },
    close() { sock.end(); }
  };
}

async function login() {
  const c = conectar();
  await c.send(null); // saludo del servidor
  await c.send('USER ' + pop3.user);
  await c.send('PASS ' + pop3.pass);
  return c;
}

async function listar() {
  const c = await login();
  try {
    const lista = await c.send('LIST', true);
    const nums = lista.split('\r\n').filter(Boolean).map(l => Number(l.split(' ')[0]));
    const out = [];
    for (const n of nums) {
      const raw = await c.send('RETR ' + n, true);
      out.push(await parsear(Buffer.from(raw, 'latin1'), n));
    }
    await c.send('QUIT');
    return out;
  } finally {
    c.close();
  }
}

async function eliminar(n) {
  const c = await login();
  try {
    await c.send('DELE ' + n);
    await c.send('QUIT'); // POP3 recién borra de verdad al hacer QUIT
  } finally {
    c.close();
  }
}

module.exports = { listar, eliminar };