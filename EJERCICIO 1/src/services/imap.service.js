const imaps = require('imap-simple');
const { imap } = require('../config');
const { parsear, fechaLocal } = require('./parser');

const CAMPOS = ['BODY', 'FROM', 'TO', 'CC', 'SUBJECT'];

const imapConfig = {
  imap: {
    user: imap.user,
    password: imap.pass,
    host: imap.host,
    port: imap.port,
    tls: true,
    authTimeout: 5000
  }
};

async function listar(campo, q, desde) {
  const connection = await imaps.connect(imapConfig);
  try {
    await connection.openBox('INBOX');
    const criterios = [];
    if (q && CAMPOS.includes(campo)) criterios.push([campo, q]);
    if (desde) criterios.push(['SINCE', fechaLocal(desde)]);
    if (!criterios.length) criterios.push('ALL');

    const messages = await connection.search(criterios, { bodies: [''], markSeen: false });
    const out = [];
    for (const item of messages) {
      const part = item.parts.find(p => p.which === '');
      out.push(await parsear(part.body, item.attributes.uid));
    }
    return out;
  } finally {
    connection.end();
  }
}

async function eliminar(uid) {
  const connection = await imaps.connect(imapConfig);
  try {
    await connection.openBox('INBOX');
    await connection.deleteMessage(uid); // marca \Deleted y hace EXPUNGE
  } finally {
    connection.end();
  }
}

module.exports = { listar, eliminar };