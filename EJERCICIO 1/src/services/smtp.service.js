const nodemailer = require('nodemailer');
const { smtp } = require('../config');

const transporter = nodemailer.createTransport({
  host: smtp.host,
  port: smtp.port,
  secure: false,
  auth: { user: smtp.user, pass: smtp.pass }
});

function enviar({ to, subject, text, inReplyTo }) {
  return transporter.sendMail({
    from: smtp.user,
    to, subject, text,
    ...(inReplyTo && { inReplyTo, references: inReplyTo }) // para responder en hilo
  });
}

module.exports = { enviar };