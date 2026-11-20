#!/usr/bin/env python3
"""
Cliente de Chat por consola (TP Comunicación de Datos).

Uso:  python3 cliente_chat.py [host] [puerto]      (por defecto localhost 5000)
Escribí /ayuda dentro del chat para ver los comandos.
"""
import base64
import getpass
import json
import os
import socket
import sys
import threading
import time

os.chdir(os.path.dirname(os.path.abspath(__file__)))

HOST = sys.argv[1] if len(sys.argv) > 1 else "localhost"
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 5000
MAX_LINE = 16 * 1024 * 1024
DOWNLOADS = "descargas"
CHATS = "conversaciones"

AYUDA = """Comandos:
  texto                      envía al canal activo
  /canal #nombre             cambia el canal activo
  /unirse #nombre            se une (o crea) un canal
  /salir #nombre             abandona un canal
  /canales                   lista los canales
  /usuarios [#canal]         usuarios conectados (o miembros de un canal)
  /msg usuario texto         mensaje privado
  /archivo usuario ruta      envía un archivo (máx. 10 MB)
  /perfil [usuario]          muestra el perfil
  /nombre Nombre Completo    cambia tu nombre
  /bio texto                 cambia tu biografía
  /foto ruta                 sube tu foto de perfil (png/jpg/gif, máx. 2 MB)
  /verfoto [usuario]         descarga la foto de perfil a ./descargas
  /historial [destino] [n]   historial del servidor (canal activo por defecto)
  /guardar                   activa/desactiva guardar la conversación en ./conversaciones
  /ayuda  /salir_chat        ayuda / desconectar"""

wlock = threading.Lock()
state = {"user": None, "chan": "#general", "save": False, "fh": None}
sock = None


def send(obj):
    data = (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")
    with wlock:
        sock.sendall(data)


def out(text):
    print(text)
    if state["save"] and state["fh"]:
        state["fh"].write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {text}\n")
        state["fh"].flush()


def safe_name(name):
    return os.path.basename(name) or "archivo"


def save_bytes(folder, name, b64):
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"{int(time.time())}_{safe_name(name)}")
    with open(path, "wb") as f:
        f.write(base64.b64decode(b64))
    return path


def on_message(m):
    t = m.get("t")
    if t == "msg":
        who = m["from"]
        if m["to"].startswith("#"):
            out(f"[{m['ts'][11:]}] {m['to']} <{who}> {m['text']}")
        else:
            out(f"[{m['ts'][11:]}] (privado) <{who}> {m['text']}")
    elif t == "info":
        out(f"* {m['text']}")
    elif t == "error":
        out(f"! {m['text']}")
    elif t == "joined":
        state["chan"] = m["ch"]
    elif t == "channels":
        out("Canales: " + ", ".join(f"{k} ({v})" for k, v in m["list"].items()))
    elif t == "users":
        where = m["ch"] or "conectados"
        out(f"Usuarios {where}: " + ", ".join(m["list"]))
    elif t == "profile":
        out(f"--- Perfil de {m['user']} ---\n  Nombre: {m['name']}\n  Bio: {m['bio']}\n"
            f"  Foto: {'sí' if m['photo'] else 'no'}\n  Estado: {'conectado' if m['online'] else 'desconectado'}\n"
            f"  Miembro desde: {m['since']}")
    elif t == "photo":
        p = save_bytes(DOWNLOADS, f"foto_{m['user']}{m['ext']}", m["data"])
        out(f"* Foto de {m['user']} guardada en {p}")
    elif t == "file":
        p = save_bytes(DOWNLOADS, m["name"], m["data"])
        out(f"* {m['from']} te envió el archivo '{m['name']}' -> guardado en {p}")
    elif t == "history":
        out(f"--- Historial de {m['target']} ---")
        for e in m["lines"]:
            dest = "" if e["to"].startswith("#") else " (privado)"
            out(f"[{e['ts']}]{dest} <{e['from']}> {e['text']}")
        out("--- fin ---")


def receiver(rf):
    try:
        while True:
            line = rf.readline(MAX_LINE)
            if not line:
                break
            on_message(json.loads(line))
    except (OSError, ValueError):
        pass
    print("\n* Conexión cerrada.")
    os._exit(0)


def read_file(path, limit):
    path = os.path.expanduser(path)
    if not os.path.isfile(path):
        out("! No existe ese archivo.")
        return None
    if os.path.getsize(path) > limit:
        out(f"! El archivo supera el límite de {limit // (1024 * 1024)} MB.")
        return None
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()


def command(line):
    parts = line.split(maxsplit=2)
    cmd = parts[0].lower()
    a1 = parts[1] if len(parts) > 1 else ""
    rest = parts[2] if len(parts) > 2 else ""

    if cmd == "/ayuda":
        print(AYUDA)
    elif cmd == "/salir_chat":
        send({"t": "quit"})
        os._exit(0)
    elif cmd == "/canal":
        state["chan"] = a1
        out(f"* Canal activo: {a1}")
    elif cmd == "/unirse":
        send({"t": "join", "ch": a1})
    elif cmd == "/salir":
        send({"t": "leave", "ch": a1})
    elif cmd == "/canales":
        send({"t": "channels"})
    elif cmd == "/usuarios":
        send({"t": "who", "ch": a1 or None})
    elif cmd == "/msg":
        if not a1 or not rest:
            return out("! Uso: /msg usuario texto")
        send({"t": "msg", "to": a1, "text": rest})
        out(f"[{time.strftime('%H:%M:%S')}] (privado a {a1}) <yo> {rest}")
    elif cmd == "/archivo":
        if not a1 or not rest:
            return out("! Uso: /archivo usuario ruta")
        b64 = read_file(rest, 10 * 1024 * 1024)
        if b64:
            send({"t": "file", "to": a1, "name": safe_name(rest), "data": b64})
    elif cmd == "/perfil":
        send({"t": "profile", "user": a1 or None})
    elif cmd == "/nombre":
        name = line.partition(" ")[2]
        send({"t": "set_profile", "name": name})
    elif cmd == "/bio":
        bio = line.partition(" ")[2]
        send({"t": "set_profile", "bio": bio})
    elif cmd == "/foto":
        path = line.partition(" ")[2]
        b64 = read_file(path, 2 * 1024 * 1024)
        if b64:
            send({"t": "set_photo", "ext": os.path.splitext(path)[1], "data": b64})
    elif cmd == "/verfoto":
        send({"t": "get_photo", "user": a1 or None})
    elif cmd == "/historial":
        target = a1 if a1 and not a1.isdigit() else state["chan"]
        n = int(a1) if a1.isdigit() else (int(rest) if rest.isdigit() else 20)
        send({"t": "history", "target": target, "n": n})
    elif cmd == "/guardar":
        state["save"] = not state["save"]
        if state["save"]:
            os.makedirs(CHATS, exist_ok=True)
            state["fh"] = open(os.path.join(CHATS, f"{state['user']}.txt"), "a", encoding="utf-8")
            print(f"* Guardando conversación en {CHATS}/{state['user']}.txt")
        else:
            if state["fh"]:
                state["fh"].close()
            print("* Guardado de conversación desactivado.")
    else:
        print("! Comando desconocido. /ayuda")


def authenticate(rf):
    while True:
        op = input("(l)ogin o (r)egistrarse: ").strip().lower()
        if op not in ("l", "r"):
            continue
        user = input("Usuario: ").strip()
        pw = getpass.getpass("Contraseña: ") if sys.stdin.isatty() else input("Contraseña: ")
        send({"t": "login" if op == "l" else "register", "user": user, "pass": pw})
        resp = json.loads(rf.readline(MAX_LINE))
        print(("* " if resp["ok"] else "! ") + resp["text"])
        if resp["ok"] and op == "l":
            state["user"] = user
            return


def main():
    global sock
    sock = socket.create_connection((HOST, PORT))
    rf = sock.makefile("rb")
    authenticate(rf)
    threading.Thread(target=receiver, args=(rf,), daemon=True).start()
    try:
        while True:
            line = input().strip()
            if not line:
                continue
            if line.startswith("/"):
                command(line)
            else:
                send({"t": "msg", "to": state["chan"], "text": line})
                out(f"[{time.strftime('%H:%M:%S')}] {state['chan']} <yo> {line}")
    except (EOFError, KeyboardInterrupt):
        try:
            send({"t": "quit"})
        except OSError:
            pass


if __name__ == "__main__":
    main()
