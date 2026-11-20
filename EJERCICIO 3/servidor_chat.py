#!/usr/bin/env python3
"""
Servidor de Chat / Mensajería instantánea (TP Comunicación de Datos).

Protocolo propio sobre TCP: un mensaje JSON por línea (UTF-8, terminado en \n).

Funcionalidades:
  - Registro e inicio de sesión (contraseñas hasheadas con PBKDF2-SHA256).
  - Múltiples canales (#general, #redes, ...) y mensajes privados.
  - Envío de archivos a un usuario determinado.
  - Información de usuario: nombre, bio y foto de perfil.
  - Conversaciones guardadas en el servidor (carpeta historial/).
  - Logging de eventos en chat_server.log.

Uso:  python3 servidor_chat.py [puerto]     (por defecto 5000)
"""
import base64
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import socket
import sys
import threading
import time

# Trabajar siempre desde la carpeta del script
os.chdir(os.path.dirname(os.path.abspath(__file__)))

HOST = "0.0.0.0"
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 5000
USERS_FILE = "usuarios.json"
HIST_DIR = "historial"
PHOTO_DIR = "fotos"
MAX_LINE = 16 * 1024 * 1024
MAX_FILE = 10 * 1024 * 1024
MAX_PHOTO = 2 * 1024 * 1024
RE_USER = re.compile(r"^[A-Za-z0-9_]{3,20}$")
RE_CHAN = re.compile(r"^#[A-Za-z0-9_-]{1,30}$")
RE_EXT = re.compile(r"^\.(png|jpg|jpeg|gif)$")

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler("chat_server.log", encoding="utf-8"), logging.StreamHandler()])
log = logging.getLogger("chat")

lock = threading.RLock()
online = {}                       # usuario -> Conn
channels = {"#general": set()}    # canal -> set(usuarios)


# ------------------------------------------------------------------ usuarios
def hash_pw(pw, salt=None):
    salt = salt or secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), 100_000)
    return f"{salt}${dk.hex()}"


def check_pw(pw, stored):
    return hmac.compare_digest(hash_pw(pw, stored.split("$")[0]), stored)


def load_users():
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_users(u):
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(u, f, indent=2, ensure_ascii=False)


users = load_users()


# ------------------------------------------------------------------ historial
def hist_path(target, me=None):
    if target.startswith("#"):
        return os.path.join(HIST_DIR, f"canal_{target[1:]}.jsonl")
    a, b = sorted([me, target])
    return os.path.join(HIST_DIR, f"privado_{a}__{b}.jsonl")


def hist_add(path, entry):
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def hist_read(path, n):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f.readlines()[-n:]]


# ------------------------------------------------------------------ conexión
class Conn:
    def __init__(self, sock, addr):
        self.sock, self.addr = sock, addr
        self.rf = sock.makefile("rb")
        self.wlock = threading.Lock()
        self.user = None

    def send(self, obj):
        data = (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")
        with self.wlock:
            try:
                self.sock.sendall(data)
            except OSError:
                pass

    def info(self, t):
        self.send({"t": "info", "text": t})

    def error(self, t):
        self.send({"t": "error", "text": t})


def now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def handle(c, m):
    t = m.get("t")
    me = c.user

    if t == "msg":
        to, text = str(m.get("to", "")), str(m.get("text", ""))[:2000]
        if not text.strip():
            return
        entry = {"ts": now(), "from": me, "to": to, "text": text}
        if RE_CHAN.match(to):
            with lock:
                if me not in channels.get(to, ()):
                    return c.error(f"No estás en {to}. Usá /unirse {to}")
                targets = [online[u] for u in channels[to] if u != me and u in online]
            hist_add(hist_path(to), entry)
            for x in targets:
                x.send({"t": "msg", **entry})
            log.info("canal %s <%s>: %s", to, me, text[:80])
        else:
            if to not in users:
                return c.error(f"El usuario '{to}' no existe.")
            hist_add(hist_path(to, me), entry)
            with lock:
                dest = online.get(to)
            if dest:
                dest.send({"t": "msg", **entry})
            else:
                c.info(f"{to} está desconectado; el mensaje quedó guardado en el historial.")
            log.info("privado %s -> %s", me, to)

    elif t == "join":
        ch = str(m.get("ch", ""))
        if not RE_CHAN.match(ch):
            return c.error("Nombre de canal inválido (ej: #redes).")
        with lock:
            new = ch not in channels
            channels.setdefault(ch, set()).add(me)
            members = [online[u] for u in channels[ch] if u != me and u in online]
        for x in members:
            x.info(f"{me} se unió a {ch}")
        c.send({"t": "joined", "ch": ch})
        c.info(f"Te uniste a {ch}" + (" (canal nuevo)" if new else ""))
        log.info("%s se unió a %s", me, ch)

    elif t == "leave":
        ch = str(m.get("ch", ""))
        with lock:
            if me not in channels.get(ch, ()):
                return c.error(f"No estás en {ch}.")
            channels[ch].discard(me)
            members = [online[u] for u in channels[ch] if u in online]
        for x in members:
            x.info(f"{me} salió de {ch}")
        c.info(f"Saliste de {ch}")

    elif t == "channels":
        with lock:
            lst = {k: len(v) for k, v in channels.items()}
        c.send({"t": "channels", "list": lst})

    elif t == "who":
        ch = m.get("ch")
        with lock:
            lst = sorted(channels.get(ch, ())) if ch else sorted(online)
        c.send({"t": "users", "ch": ch, "list": lst})

    elif t == "profile":
        u = str(m.get("user") or me)
        if u not in users:
            return c.error(f"El usuario '{u}' no existe.")
        p = users[u]
        c.send({"t": "profile", "user": u, "name": p.get("name", ""), "bio": p.get("bio", ""),
                "photo": bool(p.get("photo")), "online": u in online, "since": p.get("created", "")})

    elif t == "set_profile":
        with lock:
            if "name" in m:
                users[me]["name"] = str(m["name"])[:50]
            if "bio" in m:
                users[me]["bio"] = str(m["bio"])[:300]
            save_users(users)
        c.info("Perfil actualizado.")

    elif t == "set_photo":
        ext = str(m.get("ext", "")).lower()
        if not RE_EXT.match(ext):
            return c.error("Formato de foto no permitido (png, jpg, jpeg, gif).")
        try:
            data = base64.b64decode(m["data"], validate=True)
        except Exception:
            return c.error("Foto inválida.")
        if len(data) > MAX_PHOTO:
            return c.error("La foto supera los 2 MB.")
        os.makedirs(PHOTO_DIR, exist_ok=True)
        fname = f"{me}{ext}"
        with open(os.path.join(PHOTO_DIR, fname), "wb") as f:
            f.write(data)
        with lock:
            users[me]["photo"] = fname
            save_users(users)
        c.info("Foto de perfil actualizada.")
        log.info("%s actualizó su foto", me)

    elif t == "get_photo":
        u = str(m.get("user") or me)
        fname = users.get(u, {}).get("photo")
        if not fname:
            return c.error(f"{u} no tiene foto de perfil.")
        with open(os.path.join(PHOTO_DIR, fname), "rb") as f:
            data = base64.b64encode(f.read()).decode()
        c.send({"t": "photo", "user": u, "ext": os.path.splitext(fname)[1], "data": data})

    elif t == "file":
        to = str(m.get("to", ""))
        name = os.path.basename(str(m.get("name", "archivo")))
        try:
            raw = base64.b64decode(m["data"], validate=True)
        except Exception:
            return c.error("Archivo inválido.")
        if len(raw) > MAX_FILE:
            return c.error("El archivo supera los 10 MB.")
        with lock:
            dest = online.get(to)
        if to not in users:
            return c.error(f"El usuario '{to}' no existe.")
        if not dest:
            return c.error(f"{to} está desconectado; no se puede enviar el archivo.")
        dest.send({"t": "file", "from": me, "name": name, "data": m["data"]})
        hist_add(hist_path(to, me), {"ts": now(), "from": me, "to": to,
                                     "text": f"[archivo enviado: {name} ({len(raw)} bytes)]"})
        c.info(f"Archivo '{name}' enviado a {to}.")
        log.info("archivo %s (%d B): %s -> %s", name, len(raw), me, to)

    elif t == "history":
        target = str(m.get("target", ""))
        n = max(1, min(int(m.get("n", 20)), 200))
        if RE_CHAN.match(target):
            with lock:
                if me not in channels.get(target, ()):
                    return c.error("Tenés que estar en el canal para ver su historial.")
        elif target not in users:
            return c.error("Destino inexistente.")
        c.send({"t": "history", "target": target, "lines": hist_read(hist_path(target, me), n)})

    else:
        c.error("Comando desconocido.")


def client_thread(sock, addr):
    c = Conn(sock, addr)
    sock.settimeout(None)
    try:
        # --- autenticación
        while not c.user:
            line = c.rf.readline(MAX_LINE)
            if not line:
                return
            try:
                m = json.loads(line)
            except ValueError:
                continue
            u, pw = str(m.get("user", "")), str(m.get("pass", ""))
            if m.get("t") == "register":
                if not RE_USER.match(u):
                    c.send({"t": "auth", "ok": False, "text": "Usuario: 3-20 letras, números o _"})
                elif len(pw) < 4:
                    c.send({"t": "auth", "ok": False, "text": "Contraseña de al menos 4 caracteres."})
                else:
                    with lock:
                        if u in users:
                            c.send({"t": "auth", "ok": False, "text": "Ese usuario ya existe."})
                            continue
                        users[u] = {"pass": hash_pw(pw), "name": u, "bio": "", "photo": "", "created": now()}
                        save_users(users)
                    log.info("registro: %s desde %s", u, addr[0])
                    c.send({"t": "auth", "ok": True, "text": "Registro exitoso. Ahora iniciá sesión."})
            elif m.get("t") == "login":
                with lock:
                    ok = u in users and check_pw(pw, users[u]["pass"])
                    if ok and u in online:
                        c.send({"t": "auth", "ok": False, "text": "Ya hay una sesión abierta con ese usuario."})
                        continue
                    if ok:
                        online[u] = c
                        c.user = u
                        channels["#general"].add(u)
                if ok:
                    log.info("login: %s desde %s", u, addr[0])
                    c.send({"t": "auth", "ok": True, "text": f"Bienvenido, {u}. Estás en #general. /ayuda para ver comandos."})
                else:
                    log.warning("login fallido: %r desde %s", u, addr[0])
                    c.send({"t": "auth", "ok": False, "text": "Usuario o contraseña incorrectos."})
        with lock:
            others = [x for k, x in online.items() if k != c.user]
        for x in others:
            x.info(f"{c.user} se conectó.")
        # --- bucle principal
        while True:
            line = c.rf.readline(MAX_LINE)
            if not line:
                break
            try:
                m = json.loads(line)
                if m.get("t") == "quit":
                    break
                handle(c, m)
            except (ValueError, KeyError, TypeError):
                c.error("Mensaje mal formado.")
    except (ConnectionError, OSError):
        pass
    except Exception:
        log.exception("error interno")
    finally:
        if c.user:
            with lock:
                online.pop(c.user, None)
                for s in channels.values():
                    s.discard(c.user)
                others = list(online.values())
            for x in others:
                x.info(f"{c.user} se desconectó.")
            log.info("logout: %s", c.user)
        try:
            sock.close()
        except OSError:
            pass


def main():
    os.makedirs(HIST_DIR, exist_ok=True)
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((HOST, PORT))
    srv.listen(50)
    log.info("Servidor de chat escuchando en %s:%d", HOST, PORT)
    try:
        while True:
            s, a = srv.accept()
            threading.Thread(target=client_thread, args=(s, a), daemon=True).start()
    except KeyboardInterrupt:
        log.info("Servidor detenido")


if __name__ == "__main__":
    main()
