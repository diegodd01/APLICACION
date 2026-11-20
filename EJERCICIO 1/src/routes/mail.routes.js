const express = require('express');
const smtp = require('../services/smtp.service');
const imap = require('../services/imap.service');
const pop3 = require('../services/pop3.service');
const { filtrarLocal } = require('../services/parser');

const router = express.Router();

// Enviar / responder / reenviar
router.post('/send', async (req, res) => {
  try {
    const info = await smtp.enviar(req.body);
    res.json({ success: true, messageId: info.messageId });
  } catch (error) {
    res.status(500).json({ success: false, error: error.message });
  }
});

// Listar y buscar: ?protocol=imap|pop3&campo=BODY|FROM|TO|CC|SUBJECT&q=texto&desde=YYYY-MM-DD
router.get('/emails', async (req, res) => {
  const { protocol = 'imap', campo = 'BODY', q = '', desde = '' } = req.query;
  try {
    const emails = protocol === 'pop3'
      ? filtrarLocal(await pop3.listar(), campo, q, desde)
      : await imap.listar(campo, q, desde);
    res.json({ success: true, emails });
  } catch (error) {
    res.status(500).json({ success: false, error: error.message });
  }
});

// Eliminar: ?protocol=imap|pop3
router.delete('/emails/:id', async (req, res) => {
  const id = Number(req.params.id);
  try {
    if (req.query.protocol === 'pop3') await pop3.eliminar(id);
    else await imap.eliminar(id);
    res.json({ success: true });
  } catch (error) {
    res.status(500).json({ success: false, error: error.message });
  }
});

module.exports = router;