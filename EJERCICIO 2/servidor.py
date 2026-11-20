#!/usr/bin/env python3
"""
Servidor Web HTTP con sockets (TP Comunicación de Datos).

Características:
  1. Soporte para protocolo HTTP/1.0 y 1.1 (GET y HEAD, Connection: close).
  2. Registro de información (logging) en formato Common Log Format.
  3. Medidas de seguridad:
       - Bloqueo de acceso fuera del DocumentRoot (../, %2e%2e, symlinks).
       - Rechazo de bytes nulos, requests demasiado grandes y métodos no permitidos.
       - Cabeceras de seguridad (X-Content-Type-Options, etc.).
       - Los archivos ocultos (que empiezan con ".") no se sirven.
  4. Interfaz web de configuración en /admin (protegida con usuario y contraseña).
  5. Protección de directorios con usuario y contraseña (HTTP Basic Auth).
     Las contraseñas se guardan hasheadas (PBKDF2-SHA256), nunca en texto plano.

Uso:
    python3 servidor.py [archivo_config.json]
"""
import base64
import hashlib
import hmac
import html
import json
import mimetypes
import os
import secrets
import socket
import sys
import threading
import time
from email.utils import formatdate
from urllib.parse import parse_qs, unquote, urlsplit

# Trabajar siempre desde la carpeta del script (evita errores si se ejecuta desde "/" u otra ruta)
CONFIG_FILE = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else "config.json"
os.chdir(os.path.dirname(os.path.abspath(__file__)))
SERVER_NAME = "TPWeb/1.0"
MAX_HEADER = 16 * 1024
MAX_BODY = 64 * 1024
ADMIN_PATH = "/admin"

config_lock = threading.RLock()
log_lock = threading.Lock()
config = {}


# ----------------------------------------------------------------- contraseñas
def hash_password(password, salt=None):
    salt = salt or secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 100_000)
    return f"pbkdf2${salt}${dk.hex()}"


def check_password(password, stored):
    try:
        _, salt, _ = stored.split("$")
    except ValueError:
        return False
    return hmac.compare_digest(hash_password(password, salt), stored)


# --------------------------------------------------------------- configuración
def default_config():
    return {
        "host": "0.0.0.0",
        "port": 8080,
        "document_root": "www",
        "index_files": ["index.html", "index.htm"],
        "directory_listing": False,
        "log_file": "access.log",
        "admin_user": "admin",
        "admin_password": hash_password("admin"),
        "protected_dirs": {
            "/privado": {
                "realm": "Zona privada",
                "users": {"diego": hash_password("1234")},
            }
        },
    }


def load_config():
    global config
    with config_lock:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, encoding="utf-8") as f:
                config = json.load(f)
        else:
            config = default_config()
            save_config()
            print("[!] Se creó config.json con usuario admin / contraseña 'admin'. "
                  "CAMBIALA desde /admin.")


def save_config():
    with config_lock:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)


# --------------------------------------------------------------------- logging
def log(addr, request_line, status, size, user="-"):
    ts = time.strftime("%d/%b/%Y:%H:%M:%S %z")
    line = f'{addr[0]} - {user} [{ts}] "{request_line}" {status} {size}'
    print(line)
    with log_lock, config_lock:
        try:
            with open(config["log_file"], "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError as e:
            print(f"[!] No se pudo escribir el log: {e}")


def log_event(addr, msg):
    """Eventos de seguridad (intentos de traversal, logins fallidos, etc.)."""
    ts = time.strftime("%d/%b/%Y:%H:%M:%S %z")
    line = f"{addr[0]} [{ts}] ALERTA: {msg}"
    print(line)
    with log_lock, config_lock:
        try:
            with open(config["log_file"], "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass


# ------------------------------------------------------------------- respuestas
STATUS = {
    200: "OK", 301: "Moved Permanently", 303: "See Other", 400: "Bad Request",
    401: "Unauthorized", 403: "Forbidden", 404: "Not Found",
    405: "Method Not Allowed", 413: "Payload Too Large",
    500: "Internal Server Error", 505: "HTTP Version Not Supported",
}


def build_response(status, body=b"", content_type="text/html; charset=utf-8",
                   headers=None, head_only=False):
    if isinstance(body, str):
        body = body.encode("utf-8")
    h = {
        "Server": SERVER_NAME,
        "Date": formatdate(usegmt=True),
        "Content-Type": content_type,
        "Content-Length": str(len(body)),
        "Connection": "close",
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
    }
    if headers:
        h.update(headers)
    head = f"HTTP/1.1 {status} {STATUS.get(status, '')}\r\n"
    head += "".join(f"{k}: {v}\r\n" for k, v in h.items()) + "\r\n"
    return head.encode("latin-1"), (b"" if head_only else body), len(body)


def error_page(status, extra=""):
    t = f"{status} {STATUS[status]}"
    return (f"<!doctype html><html><head><meta charset='utf-8'><title>{t}</title></head>"
            f"<body><h1>{t}</h1><p>{html.escape(extra)}</p><hr>{SERVER_NAME}</body></html>")


# -------------------------------------------------------------------- seguridad
def resolve_path(url_path):
    """Convierte la ruta de la URL en una ruta de archivo dentro del DocumentRoot.
    Devuelve None si intenta salir del DocumentRoot."""
    with config_lock:
        root = os.path.realpath(config["document_root"])
    rel = unquote(url_path)
    if "\x00" in rel:
        return None
    rel = rel.lstrip("/")
    full = os.path.realpath(os.path.join(root, rel))  # resuelve .. y symlinks
    if full != root and not full.startswith(root + os.sep):
        return None
    # No servir archivos/directorios ocultos
    rel_parts = os.path.relpath(full, root).split(os.sep)
    if any(p.startswith(".") and p != "." for p in rel_parts):
        return None
    return full


def normalize_url(path):
    """Normaliza la ruta de la URL para comparar con directorios protegidos."""
    parts = []
    for p in unquote(path).split("/"):
        if p in ("", "."):
            continue
        if p == "..":
            if parts:
                parts.pop()
            continue
        parts.append(p)
    return "/" + "/".join(parts)


def find_protection(url_path):
    n = normalize_url(url_path).lower()
    best = None
    with config_lock:
        for d, info in config["protected_dirs"].items():
            dn = normalize_url(d).lower()
            if n == dn or n.startswith(dn.rstrip("/") + "/"):
                if best is None or len(dn) > len(best[0]):
                    best = (dn, info)
    return best[1] if best else None


def parse_basic_auth(headers):
    auth = headers.get("authorization", "")
    if not auth.lower().startswith("basic "):
        return None, None
    try:
        raw = base64.b64decode(auth[6:].strip()).decode("utf-8")
        user, _, pwd = raw.partition(":")
        return user, pwd
    except Exception:
        return None, None


def authenticate(headers, users):
    user, pwd = parse_basic_auth(headers)
    if user is None:
        return None
    stored = users.get(user)
    # Se hashea siempre para evitar diferencias de tiempo entre usuario válido/inválido
    if stored is None:
        hash_password(pwd)
        return None
    return user if check_password(pwd, stored) else None


def unauthorized(realm):
    h, b, n = build_response(
        401, error_page(401, "Se requiere autenticación."),
        headers={"WWW-Authenticate": f'Basic realm="{realm}", charset="UTF-8"'})
    return h, b, n


# ------------------------------------------------------------- listado / archivos
def directory_listing(full, url_path):
    items = sorted(os.listdir(full), key=str.lower)
    rows = []
    if normalize_url(url_path) != "/":
        rows.append("<li><a href='../'>../</a></li>")
    for name in items:
        if name.startswith("."):
            continue
        suf = "/" if os.path.isdir(os.path.join(full, name)) else ""
        e = html.escape(name)
        rows.append(f"<li><a href='{html.escape(name, quote=True)}{suf}'>{e}{suf}</a></li>")
    t = html.escape(unquote(url_path))
    return (f"<!doctype html><html><head><meta charset='utf-8'><title>Índice de {t}</title></head>"
            f"<body><h1>Índice de {t}</h1><ul>{''.join(rows)}</ul><hr>{SERVER_NAME}</body></html>")


def serve_static(method, url_path, headers):
    """Devuelve (head, body, size, status, user)."""
    head_only = method == "HEAD"
    user = "-"

    prot = find_protection(url_path)
    if prot is not None:
        u = authenticate(headers, prot["users"])
        if u is None:
            h, b, n = unauthorized(prot.get("realm", "Zona privada"))
            return h, (b if not head_only else b""), n, 401, "-"
        user = u

    full = resolve_path(url_path)
    if full is None:
        return (*build_response(403, error_page(403, "Acceso denegado."), head_only=head_only), 403, user)

    if os.path.isdir(full):
        if not url_path.endswith("/"):
            h, b, n = build_response(301, b"", headers={"Location": url_path + "/"}, head_only=head_only)
            return h, b, n, 301, user
        with config_lock:
            indexes = list(config["index_files"])
            listing = config["directory_listing"]
        for idx in indexes:
            cand = os.path.join(full, idx)
            if os.path.isfile(cand):
                full = cand
                break
        else:
            if listing:
                h, b, n = build_response(200, directory_listing(full, url_path), head_only=head_only)
                return h, b, n, 200, user
            return (*build_response(403, error_page(403, "Listado de directorio deshabilitado."),
                                    head_only=head_only), 403, user)

    if not os.path.isfile(full):
        return (*build_response(404, error_page(404, "El recurso no existe."), head_only=head_only), 404, user)

    try:
        with open(full, "rb") as f:
            data = f.read()
    except OSError:
        return (*build_response(403, error_page(403), head_only=head_only), 403, user)

    ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
    if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
        ctype += "; charset=utf-8"
    mtime = formatdate(os.path.getmtime(full), usegmt=True)
    h, b, n = build_response(200, data, ctype, {"Last-Modified": mtime}, head_only)
    return h, b, n, 200, user


# --------------------------------------------------------------- interfaz /admin
def admin_page(msg=""):
    with config_lock:
        c = json.loads(json.dumps(config))
    chk = "checked" if c["directory_listing"] else ""
    prot_rows = ""
    for d, info in c["protected_dirs"].items():
        users = ", ".join(html.escape(u) for u in info["users"]) or "(sin usuarios)"
        prot_rows += (
            f"<tr><td>{html.escape(d)}</td><td>{html.escape(info.get('realm',''))}</td><td>{users}</td>"
            f"<td><form method='post' style='margin:0'><input type='hidden' name='action' value='del_dir'>"
            f"<input type='hidden' name='dir' value='{html.escape(d, quote=True)}'>"
            f"<button>Quitar protección</button></form></td></tr>")
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>Administración</title>
<style>body{{font-family:sans-serif;max-width:900px;margin:2rem auto;padding:0 1rem}}
fieldset{{margin:1rem 0}}label{{display:block;margin:.4rem 0}}input[type=text],input[type=password],input[type=number]{{width:320px}}
table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #ccc;padding:.4rem;text-align:left}}
.msg{{background:#e7f5e7;border:1px solid #9c9;padding:.5rem}}</style></head><body>
<h1>Administración del servidor</h1>{f"<p class='msg'>{html.escape(msg)}</p>" if msg else ""}

<fieldset><legend>Parámetros generales</legend>
<form method="post"><input type="hidden" name="action" value="general">
<label>Host: <input type="text" name="host" value="{html.escape(c['host'], quote=True)}"></label>
<label>Puerto (requiere reiniciar): <input type="number" name="port" min="1" max="65535" value="{c['port']}"></label>
<label>DocumentRoot: <input type="text" name="document_root" value="{html.escape(c['document_root'], quote=True)}"></label>
<label>Archivos índice (separados por coma): <input type="text" name="index_files" value="{html.escape(', '.join(c['index_files']), quote=True)}"></label>
<label>Archivo de log: <input type="text" name="log_file" value="{html.escape(c['log_file'], quote=True)}"></label>
<label><input type="checkbox" name="directory_listing" {chk}> Permitir listado de directorios</label>
<button>Guardar</button></form></fieldset>

<fieldset><legend>Credenciales de administrador</legend>
<form method="post"><input type="hidden" name="action" value="admin_cred">
<label>Usuario: <input type="text" name="admin_user" value="{html.escape(c['admin_user'], quote=True)}"></label>
<label>Nueva contraseña: <input type="password" name="admin_password"></label>
<button>Cambiar</button></form></fieldset>

<fieldset><legend>Directorios protegidos</legend>
<table><tr><th>Directorio (URL)</th><th>Realm</th><th>Usuarios</th><th></th></tr>{prot_rows}</table>
<h3>Agregar/actualizar directorio y usuario</h3>
<form method="post"><input type="hidden" name="action" value="add_user">
<label>Directorio (ej: /privado): <input type="text" name="dir"></label>
<label>Realm: <input type="text" name="realm" value="Zona privada"></label>
<label>Usuario: <input type="text" name="user"></label>
<label>Contraseña: <input type="password" name="password"></label>
<button>Guardar</button></form>
<h3>Eliminar usuario de un directorio</h3>
<form method="post"><input type="hidden" name="action" value="del_user">
<label>Directorio: <input type="text" name="dir"></label>
<label>Usuario: <input type="text" name="user"></label>
<button>Eliminar</button></form></fieldset>
<p><a href="{ADMIN_PATH}/log">Ver últimas líneas del log</a></p>
</body></html>"""


def admin_log_page():
    with config_lock:
        path = config["log_file"]
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()[-100:]
    except OSError:
        lines = ["(log vacío)"]
    return ("<!doctype html><meta charset='utf-8'><title>Log</title><body style='font-family:monospace'>"
            f"<h2>Últimas {len(lines)} líneas</h2><p><a href='{ADMIN_PATH}'>Volver</a></p>"
            f"<pre>{html.escape(''.join(lines))}</pre></body>")


def admin_apply(form):
    f = {k: v[0].strip() for k, v in form.items()}
    action = f.get("action")
    with config_lock:
        if action == "general":
            try:
                port = int(f["port"])
                assert 1 <= port <= 65535
            except (KeyError, ValueError, AssertionError):
                return "Puerto inválido."
            root = f.get("document_root", "")
            if not os.path.isdir(root):
                return f"El DocumentRoot '{root}' no existe."
            config["host"] = f.get("host", "0.0.0.0") or "0.0.0.0"
            config["port"] = port
            config["document_root"] = root
            config["index_files"] = [x.strip() for x in f.get("index_files", "").split(",") if x.strip()]
            config["log_file"] = f.get("log_file") or "access.log"
            config["directory_listing"] = "directory_listing" in f
            msg = "Configuración guardada (host/puerto se aplican al reiniciar)."
        elif action == "admin_cred":
            if not f.get("admin_user"):
                return "El usuario no puede estar vacío."
            config["admin_user"] = f["admin_user"]
            if f.get("admin_password"):
                config["admin_password"] = hash_password(f["admin_password"])
            msg = "Credenciales actualizadas."
        elif action == "add_user":
            d = normalize_url(f.get("dir", ""))
            if d == "/" or d.lower().startswith(ADMIN_PATH):
                return "Directorio inválido."
            if not f.get("user") or not f.get("password"):
                return "Usuario y contraseña son obligatorios."
            entry = config["protected_dirs"].setdefault(d, {"realm": "Zona privada", "users": {}})
            entry["realm"] = f.get("realm") or entry["realm"]
            entry["users"][f["user"]] = hash_password(f["password"])
            msg = f"Usuario '{f['user']}' agregado a {d}."
        elif action == "del_user":
            d = normalize_url(f.get("dir", ""))
            entry = config["protected_dirs"].get(d)
            if not entry or f.get("user") not in entry["users"]:
                return "No existe ese directorio/usuario."
            del entry["users"][f["user"]]
            msg = "Usuario eliminado."
        elif action == "del_dir":
            config["protected_dirs"].pop(f.get("dir", ""), None)
            msg = "Protección eliminada."
        else:
            return "Acción desconocida."
        save_config()
    return msg


def handle_admin(method, path, headers, body):
    with config_lock:
        users = {config["admin_user"]: config["admin_password"]}
    if authenticate(headers, users) is None:
        return (*unauthorized("Administración"), 401, "-")
    user = parse_basic_auth(headers)[0]
    head_only = method == "HEAD"
    if path.rstrip("/") == ADMIN_PATH + "/log":
        h, b, n = build_response(200, admin_log_page(), head_only=head_only)
        return h, b, n, 200, user
    if method == "POST":
        form = parse_qs(body.decode("utf-8", "replace"))
        msg = admin_apply(form)
        # Patrón Post/Redirect/Get no es necesario: se muestra la página directamente
        h, b, n = build_response(200, admin_page(msg))
        return h, b, n, 200, user
    h, b, n = build_response(200, admin_page(), head_only=head_only)
    return h, b, n, 200, user


# --------------------------------------------------------------------- conexión
def read_request(conn):
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = conn.recv(4096)
        if not chunk:
            return None
        data += chunk
        if len(data) > MAX_HEADER:
            raise OverflowError
    head, _, rest = data.partition(b"\r\n\r\n")
    lines = head.decode("latin-1").split("\r\n")
    request_line = lines[0]
    headers = {}
    for ln in lines[1:]:
        if ":" in ln:
            k, _, v = ln.partition(":")
            headers[k.strip().lower()] = v.strip()
    length = int(headers.get("content-length", "0") or 0)
    if length > MAX_BODY:
        raise OverflowError
    while len(rest) < length:
        chunk = conn.recv(4096)
        if not chunk:
            break
        rest += chunk
    return request_line, headers, rest[:length]


def handle_client(conn, addr):
    request_line = "-"
    try:
        conn.settimeout(10)
        try:
            req = read_request(conn)
        except OverflowError:
            h, b, n = build_response(413, error_page(413))
            conn.sendall(h + b)
            log(addr, request_line, 413, n)
            return
        except (ValueError, UnicodeDecodeError):
            h, b, n = build_response(400, error_page(400))
            conn.sendall(h + b)
            log(addr, request_line, 400, n)
            return
        if req is None:
            return
        request_line, headers, body = req
        parts = request_line.split()
        if len(parts) != 3:
            h, b, n = build_response(400, error_page(400))
            conn.sendall(h + b)
            log(addr, request_line, 400, n)
            return
        method, target, version = parts
        if not version.startswith("HTTP/1."):
            h, b, n = build_response(505, error_page(505))
            conn.sendall(h + b)
            log(addr, request_line, 505, n)
            return
        url_path = urlsplit(target).path or "/"
        if "\x00" in unquote(url_path):
            h, b, n = build_response(400, error_page(400))
            conn.sendall(h + b)
            log_event(addr, f"byte nulo en URL: {target!r}")
            log(addr, request_line, 400, n)
            return

        is_admin = normalize_url(url_path).lower().startswith(ADMIN_PATH)
        allowed = ("GET", "HEAD", "POST") if is_admin else ("GET", "HEAD")
        if method not in allowed:
            h, b, n = build_response(405, error_page(405), headers={"Allow": ", ".join(allowed)})
            conn.sendall(h + b)
            log(addr, request_line, 405, n)
            return

        if is_admin:
            head, content, size, status, user = handle_admin(method, url_path, headers, body)
        else:
            head, content, size, status, user = serve_static(method, url_path, headers)

        if status == 403 and resolve_path(url_path) is None:
            log_event(addr, f"intento de acceso fuera del DocumentRoot: {target!r}")
        if status == 401 and "authorization" in headers:
            log_event(addr, f"autenticación fallida en {url_path!r}")

        conn.sendall(head + content)
        log(addr, request_line, status, size, user)
    except (socket.timeout, ConnectionError):
        pass
    except Exception as e:  # nunca revelar detalles internos al cliente
        try:
            h, b, n = build_response(500, error_page(500))
            conn.sendall(h + b)
            log(addr, request_line, 500, n)
        except OSError:
            pass
        print(f"[!] Error interno: {e!r}")
    finally:
        conn.close()


def main():
    load_config()
    with config_lock:
        host, port, root = config["host"], config["port"], config["document_root"]
    os.makedirs(root, exist_ok=True)
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((host, port))
    srv.listen(50)
    print(f"{SERVER_NAME} escuchando en http://{host}:{port}  (DocumentRoot: {os.path.realpath(root)})")
    print(f"Administración: http://localhost:{port}{ADMIN_PATH}")
    try:
        while True:
            conn, addr = srv.accept()
            threading.Thread(target=handle_client, args=(conn, addr), daemon=True).start()
    except KeyboardInterrupt:
        print("\nServidor detenido.")
    finally:
        srv.close()


if __name__ == "__main__":
    main()
