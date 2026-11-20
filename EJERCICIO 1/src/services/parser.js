const { simpleParser } = require('mailparser');

async function parsear(raw, id) {
  const p = await simpleParser(raw);
  return {
    id,
    messageId: p.messageId || '',
    subject: p.subject || '(sin asunto)',
    from: p.from ? p.from.text : '',
    to: p.to ? p.to.text : '',
    date: p.date,
    text: p.text || ''
  };
}

// "2026-11-12" -> Date a medianoche en hora local (evita el corrimiento de zona horaria)
function fechaLocal(str) {
  const [y, m, d] = str.split('-').map(Number);
  return new Date(y, m - 1, d);
}

// POP3 no tiene búsqueda en el servidor: se filtra acá
function filtrarLocal(emails, campo, q, desde) {
  const map = { BODY: 'text', FROM: 'from', TO: 'to', CC: 'to', SUBJECT: 'subject' };
  return emails.filter(e => {
    if (q && map[campo] && !String(e[map[campo]]).toLowerCase().includes(q.toLowerCase())) return false;
    if (desde && new Date(e.date) < fechaLocal(desde)) return false;
    return true;
  });
}

module.exports = { parsear, filtrarLocal, fechaLocal };