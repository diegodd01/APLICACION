let emails = [];
let inReplyTo = null;
let timer = null;
let controller = null; // para cancelar la búsqueda anterior

const $ = id => document.getElementById(id);

const esc = s => String(s ?? '').replace(/[&<>"']/g,
  c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

function setEstado(texto, tipo = '') {
  $('estado').textContent = texto;
  $('estado').className = 'estado ' + tipo;
}

// "Rosa <rosa@x.com>" -> "rosa@x.com"
function direccion(texto) {
  const m = String(texto).match(/<([^>]+)>/);
  return m ? m[1] : texto;
}

function buscar() {
  clearTimeout(timer);
  timer = setTimeout(cargar, 400); // espera a que dejes de escribir
}

/* ---------- Enviar / limpiar ---------- */
async function enviar() {
  setEstado('Enviando...', 'wait');
  try {
    const res = await fetch('/api/send', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        to: $('to').value,
        subject: $('subject').value,
        text: $('text').value,
        inReplyTo
      })
    });
    const data = await res.json();
    if (!data.success) throw new Error(data.error);
    setEstado('Correo enviado', 'ok');
    limpiar();
    cargar();
  } catch (err) {
    setEstado('Error al enviar', 'error');
    alert('Error: ' + err.message);
  }
}

function limpiar() {
  $('to').value = '';
  $('subject').value = '';
  $('text').value = '';
  inReplyTo = null;
}

/* ---------- Responder / reenviar / eliminar ---------- */
function citar(e) {
  return `\n\n--- Mensaje original ---\nDe: ${e.from}\nFecha: ${new Date(e.date).toLocaleString()}\nAsunto: ${e.subject}\n\n${e.text}`;
}

function responder(i) {
  const e = emails[i];
  $('to').value = direccion(e.from);
  $('subject').value = /^re:/i.test(e.subject) ? e.subject : 'Re: ' + e.subject;
  $('text').value = citar(e).replace(/^/gm, '> ');
  inReplyTo = e.messageId || null;
  setEstado('Respondiendo', 'wait');
  window.scrollTo(0, 0);
}

function reenviar(i) {
  const e = emails[i];
  $('to').value = '';
  $('subject').value = /^fwd:/i.test(e.subject) ? e.subject : 'Fwd: ' + e.subject;
  $('text').value = citar(e);
  inReplyTo = null;
  setEstado('Reenviando', 'wait');
  window.scrollTo(0, 0);
}

async function eliminar(i) {
  if (!confirm('¿Eliminar este correo?')) return;
  setEstado('Eliminando...', 'wait');
  try {
    const res = await fetch(`/api/emails/${emails[i].id}?protocol=${$('protocol').value}`, { method: 'DELETE' });
    const data = await res.json();
    if (!data.success) throw new Error(data.error);
    cargar();
  } catch (err) {
    setEstado('Error al eliminar', 'error');
    alert('Error: ' + err.message);
  }
}

/* ---------- Listar / buscar ---------- */
function render() {
  $('lista').innerHTML = emails.map((e, i) => `
    <article class="email">
      <div class="meta">
        <span class="from">${esc(e.from)}</span>
        <span>${e.date ? new Date(e.date).toLocaleString() : ''}</span>
      </div>
      <p class="subject">${esc(e.subject)}</p>
      <p class="body">${esc(e.text.slice(0, 200))}${e.text.length > 200 ? '…' : ''}</p>
      <div class="acciones">
        <button class="btn small" onclick="responder(${i})">Responder</button>
        <button class="btn small" onclick="reenviar(${i})">Reenviar</button>
        <button class="btn small danger" onclick="eliminar(${i})">Eliminar</button>
      </div>
    </article>`).join('') || '<p class="vacio">No se encontraron correos.</p>';
}

async function cargar() {
  if (controller) controller.abort(); // cancela la búsqueda anterior
  controller = new AbortController();

  const params = new URLSearchParams({
    protocol: $('protocol').value,
    campo: $('campo').value,
    q: $('q').value.trim(),
    desde: $('desde').value
  });

  setEstado('Buscando...', 'wait');
  try {
    const res = await fetch('/api/emails?' + params, { signal: controller.signal });
    const data = await res.json();
    if (!data.success) throw new Error(data.error);

    emails = data.emails.sort((a, b) => new Date(b.date) - new Date(a.date)); // más nuevos primero
    render();
    setEstado(`${emails.length} correo(s)`, 'ok');
  } catch (err) {
    if (err.name === 'AbortError') return; // fue reemplazada por otra búsqueda
    $('lista').innerHTML = `<p class="vacio">Error: ${esc(err.message)}</p>`;
    setEstado('Error', 'error');
  }
}

cargar();