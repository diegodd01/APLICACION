require('dotenv').config();

module.exports = {
  port: process.env.PORT || 3000,
  smtp: {
    host: process.env.SMTP_HOST,
    port: Number(process.env.SMTP_PORT),
    user: process.env.SMTP_USER,
    pass: process.env.SMTP_PASS
  },
  imap: {
    host: process.env.IMAP_HOST,
    port: Number(process.env.IMAP_PORT),
    user: process.env.IMAP_USER,
    pass: process.env.IMAP_PASS
  },
  pop3: {
    host: process.env.POP3_HOST,
    port: Number(process.env.POP3_PORT),
    user: process.env.POP3_USER,
    pass: process.env.POP3_PASS,
    tls: process.env.POP3_TLS !== 'false' // 'false' = sin TLS (servidor local de prueba)
  }
};