// Servidor POP3 local de prueba (sin TLS) para probar el cliente sin depender de internet.
// Uso:  node tools/pop3-local.js
// Usuario/contraseña por defecto: tp / tp123 (cambiables con POP3_LOCAL_USER / POP3_LOCAL_PASS).
// Implementa el RFC 1939: USER, PASS, STAT, LIST, RETR, DELE, NOOP, RSET, QUIT y CAPA.
const net = require('net');

const PORT = Number(process.env.POP3_LOCAL_PORT) || 1100;
const USER = process.env.POP3_LOCAL_USER || 'tp';
const PASS = process.env.POP3_LOCAL_PASS || 'tp123';

const hace = h => new Date(Date.now() - h * 3600 * 1000).toUTCString();

// Casilla de ejemplo (se restaura cada vez que se reinicia el servidor)
const muestras = [
  { from: 'Rosa <rosa12@ethereal.email>', subject: 'TP-RD', fecha: hace(1),
    body: 'Hola, este es un mensaje de prueba para el trabajo práctico.' },
  { from: 'Docente Redes <docente@utn.example>', subject: 'Consigna del TP de correo', fecha: hace(26),
    body: 'Recuerden implementar SMTP, IMAP y POP3.\r\n.Esta línea empieza con un punto (prueba de byte-stuffing).\r\nFin del mensaje.' },
  { from: 'Compañero <companero@example.com>', subject: 'Reunión de grupo', fecha: hace(50),
    body: 'Nos juntamos mañana a las 18 para terminar la presentación.' },
  { from: 'Soporte <soporte@example.org>', subject: 'Prueba con acentos: ñandú, camión, qué', fecha: hace(75),
    body: 'Mensaje con caracteres especiales: áéíóú ñ ¿? ¡! — verifica la codificación UTF-8.' }
];

function armar(m, i) {
  return [
    `From: ${m.from}`,
    'To: tp@local.test',
    `Subject: ${m.subject}`,
    `Date: ${m.fecha}`,
    `Message-ID: <local-${i}-${Date.now()}@pop3.local>`,
    'MIME-Version: 1.0',
    'Content-Type: text/plain; charset=utf-8',
    'Content-Transfer-Encoding: 8bit',
    '',
    m.body
  ].join('\r\n');
}

let buzon = muestras.map((m, i) => Buffer.from(armar(m, i + 1), 'utf8'));

const server = net.createServer(sock => {
  const peer = `${sock.remoteAddress}:${sock.remotePort}`;
  console.log(`\n== Conexión de ${peer}`);
  let estado = 'AUTH', user = null, buf = '';
  const borrados = new Set();
  const w = t => { console.log('S: ' + t.split('\r\n')[0]); sock.write(t); };
  const visibles = () => buzon.map((b, i) => ({ n: i + 1, b })).filter(x => !borrados.has(x.n));
  const num = a => { const n = Number(a); return Number.isInteger(n) && n >= 1 && n <= buzon.length && !borrados.has(n) ? n : null; };

  w('+OK POP3 local de prueba listo\r\n');

  sock.on('data', d => {
    buf += d.toString('latin1');
    let i;
    while ((i = buf.indexOf('\n')) !== -1) {
      const linea = buf.slice(0, i).replace(/\r$/, '');
      buf = buf.slice(i + 1);
      comando(linea);
    }
  });

  function comando(linea) {
    const [cmdRaw, ...resto] = linea.split(' ');
    const cmd = cmdRaw.toUpperCase();
    const arg = resto.join(' ');
    console.log('C: ' + (cmd === 'PASS' ? 'PASS ****' : linea));

    if (cmd === 'CAPA') return w('+OK\r\nUSER\r\n.\r\n');
    if (cmd === 'NOOP') return w('+OK\r\n');
    if (cmd === 'QUIT') {
      if (estado === 'TRANS') buzon = buzon.filter((_, i) => !borrados.has(i + 1)); // el borrado se confirma al hacer QUIT
      w('+OK hasta luego\r\n');
      return sock.end();
    }
    if (estado === 'AUTH') {
      if (cmd === 'USER') { user = arg; return w('+OK\r\n'); }
      if (cmd === 'PASS') {
        if (user === USER && arg === PASS) {
          estado = 'TRANS';
          return w(`+OK maildrop tiene ${buzon.length} mensajes\r\n`);
        }
        user = null;
        return w('-ERR credenciales invalidas\r\n');
      }
      return w('-ERR autenticarse primero\r\n');
    }
    // estado TRANSACTION
    const v = visibles();
    if (cmd === 'STAT') return w(`+OK ${v.length} ${v.reduce((s, x) => s + x.b.length, 0)}\r\n`);
    if (cmd === 'LIST') {
      if (arg) {
        const n = num(arg);
        return n ? w(`+OK ${n} ${buzon[n - 1].length}\r\n`) : w('-ERR no existe ese mensaje\r\n');
      }
      return w(`+OK ${v.length} mensajes\r\n` + v.map(x => `${x.n} ${x.b.length}\r\n`).join('') + '.\r\n');
    }
    if (cmd === 'RETR') {
      const n = num(arg);
      if (!n) return w('-ERR no existe ese mensaje\r\n');
      const cuerpo = buzon[n - 1].toString('utf8').replace(/^\./gm, '..'); // byte-stuffing
      console.log(`S: +OK ${buzon[n - 1].length} octetos (mensaje ${n})`);
      return sock.write(Buffer.from(`+OK ${buzon[n - 1].length} octetos\r\n${cuerpo}\r\n.\r\n`, 'utf8'));
    }
    if (cmd === 'DELE') {
      const n = num(arg);
      if (!n) return w('-ERR no existe ese mensaje\r\n');
      borrados.add(n);
      return w(`+OK mensaje ${n} marcado para borrar\r\n`);
    }
    if (cmd === 'RSET') { borrados.clear(); return w('+OK\r\n'); }
    w('-ERR comando desconocido\r\n');
  }

  sock.on('error', () => {});
  sock.on('close', () => console.log(`== Conexión cerrada ${peer}`));
});

server.listen(PORT, '127.0.0.1', () =>
  console.log(`Servidor POP3 local en 127.0.0.1:${PORT}  (usuario: ${USER}, contraseña: ${PASS})`));
