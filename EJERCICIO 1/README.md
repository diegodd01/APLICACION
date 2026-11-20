# Cliente de correo web (SMTP / IMAP / POP3)

TP de Redes de datos. Cliente de correo con soporte SMTP, IMAP y POP3, que permite enviar, responder, reenviar, eliminar y buscar correos.

## Instalación

```bash
npm install
```

Crear un archivo `.env` en la raíz con:

```
PORT=3000
SMTP_HOST=
SMTP_PORT=
SMTP_USER=
SMTP_PASS=
IMAP_HOST=
IMAP_PORT=
IMAP_USER=
IMAP_PASS=
POP3_HOST=
POP3_PORT=
POP3_USER=
POP3_PASS=
```

## Uso

```bash
node src/server.js
```

Abrir http://localhost:3000

## Estructura

- `src/services/`: un módulo por protocolo (SMTP, IMAP, POP3) y el parser de mails
- `src/routes/`: endpoints de la API
- `public/`: interfaz web