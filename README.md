# Trabajo Práctico – Capa de Aplicación (Redes de Información)

Implementación de cuatro aplicaciones de red correspondientes a los protocolos de la capa de aplicación: **Correo Electrónico (SMTP/IMAP/POP3)**, **Servidor Web (HTTP)**, **Chat Cliente/Servidor** y **Cliente FTP**.

## Estructura del repositorio

```text
APLICACION/
├── EJERCICIO 1/              # Cliente de correo web (Node.js)
├── EJERCICIO 2/
│   └── servidor.py           # Servidor Web HTTP (Python)
├── EJERCICIO 3/
│   ├── servidor_chat.py      # Servidor de Chat (Python)
│   └── cliente_chat.py       # Cliente de Chat por consola (Python)
└── EJERCICIO 4/
    └── cliente_ftp.py        # Cliente FTP por consola (Python)
```

## Requisitos generales

- **Node.js** (v18 o superior) y **npm** para el Ejercicio 1.
- **Python 3.8+** para los Ejercicios 2, 3 y 4 (utilizan únicamente la biblioteca estándar, sin dependencias externas).

---

## 1. Cliente de Correo Electrónico (`EJERCICIO 1/`)

Aplicación web desarrollada en Node.js y Express que implementa un cliente de correo con soporte para envío, recepción y gestión de mensajes.

### Características
- Soporte para **SMTP**, **IMAP** y **POP3** (incluye servidor POP3 local en `tools/pop3-local.js` para pruebas).
- Funciones para redactar, responder, reenviar y eliminar correos.
- Búsqueda de mensajes por distintos criterios (cuerpo, destinatarios, asunto, etc.).
- Interfaz web servida desde `public/`.

### Ejecución
```bash
cd "EJERCICIO 1"
npm install
# Configurar las credenciales y servidores en el archivo .env
node src/server.js
```
Para probar POP3 en entorno local, ejecutar en otra terminal:
```bash
cd "EJERCICIO 1"
node tools/pop3-local.js
```

---

## 2. Servidor Web HTTP (`EJERCICIO 2/servidor.py`)

Servidor web implementado con sockets TCP puros en Python, compatible con HTTP/1.0 y HTTP/1.1 (`GET` y `HEAD`).

### Características
- **Logging:** registro de peticiones en formato *Common Log Format* (`access.log`) y alertas de seguridad.
- **Seguridad:** bloqueo de *path traversal* fuera del `DocumentRoot` (`../`, `%2e%2e`, enlaces simbólicos), rechazo de archivos ocultos y cabeceras de seguridad (`X-Content-Type-Options`, `X-Frame-Options`).
- **Panel de administración:** interfaz web en `/admin` para modificar parámetros generales, credenciales y directorios protegidos, además de consultar el log (`/admin/log`).
- **Protección de directorios:** autenticación *HTTP Basic Auth* con contraseñas hasheadas mediante `PBKDF2-SHA256`.

### Ejecución
```bash
cd "EJERCICIO 2"
python3 servidor.py [archivo_config.json]
```
- Por defecto escucha en `http://localhost:8080` y sirve la carpeta `www/`.
- Al ejecutarse por primera vez genera `config.json` con acceso a `/admin` (usuario: `admin`, contraseña: `admin`) y un directorio protegido de ejemplo en `/privado`.

---

## 3. Aplicación Cliente/Servidor de Chat (`EJERCICIO 3/`)

Sistema de mensajería instantánea sobre sockets TCP utilizando un protocolo basado en mensajes JSON delimitados por salto de línea.

### Características
- Registro e inicio de sesión con contraseñas hasheadas (`PBKDF2-SHA256`).
- Soporte para múltiples canales (`#general`, `#redes`, etc.) y mensajes privados.
- Envío de archivos entre usuarios conectados (hasta 10 MB, guardados en `descargas/`).
- Gestión de perfil de usuario: nombre, biografía y foto de perfil (hasta 2 MB).
- Guardado de conversaciones tanto en el servidor (`historial/`) como en el cliente (`conversaciones/`).
- Registro de eventos en `chat_server.log`.

### Ejecución
1. Iniciar el servidor (puerto `5000` por defecto):
   ```bash
   cd "EJERCICIO 3"
   python3 servidor_chat.py [puerto]
   ```
2. Conectar uno o más clientes:
   ```bash
   cd "EJERCICIO 3"
   python3 cliente_chat.py [host] [puerto]
   ```
3. Dentro del chat, escribir `/ayuda` para listar todos los comandos disponibles (`/unirse`, `/canal`, `/msg`, `/archivo`, `/perfil`, `/foto`, `/historial`, `/guardar`, etc.).

---

## 4. Cliente FTP (`EJERCICIO 4/cliente_ftp.py`)

Cliente FTP por línea de comandos implementado directamente sobre sockets TCP (RFC 959), gestionando el canal de control y el canal de datos en modo pasivo (`PASV`).

### Características
- Soporte para los comandos más comunes de FTP: `ls`, `cd`, `cdup`, `pwd`, `mkdir`, `rmdir`, `rm`, `mv`, `binary`, `ascii`, `syst`, `noop`, `raw` y `quit`.
- Subida (`put` / `STOR`) y descarga (`get` / `RETR`) de archivos.
- Comandos locales auxiliares (`lls`, `lpwd`, `lcd`).

### Ejecución
```bash
cd "EJERCICIO 4"
python3 cliente_ftp.py [host] [puerto]
```

Ejemplo de prueba contra un servidor público:
```bash
python3 cliente_ftp.py test.rebex.net 21
# Usuario: demo | Contraseña: password
```