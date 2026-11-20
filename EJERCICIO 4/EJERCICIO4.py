#!/usr/bin/env python3
"""
Cliente FTP por consola con sockets TCP (TP Comunicación de Datos).

Características:
  - Implementación directa del protocolo FTP (RFC 959) sobre sockets.
  - Canal de control (puerto 21 por defecto) y canal de datos en modo pasivo (PASV).
  - Soporte para los comandos más comunes: ls, cd, pwd, mkdir, rmdir, rm, mv,
    binary, ascii, syst, noop, quit, etc.
  - Subida (STOR) y bajada (RETR) de archivos.

Uso:
    python3 cliente_ftp.py [host] [puerto]
"""
import getpass
import os
import re
import shlex
import socket
import sys

os.chdir(os.path.dirname(os.path.abspath(__file__)))

AYUDA = """Comandos disponibles:
  ls [ruta]                  lista archivos del directorio remoto (LIST)
  cd <dir>                   cambia de directorio remoto (CWD)
  cdup                       sube un nivel en el directorio remoto (CDUP)
  pwd                        muestra el directorio remoto actual (PWD)
  get <remoto> [local]       descarga un archivo del servidor (RETR)
  put <local> [remoto]       sube un archivo al servidor (STOR)
  mkdir <dir>                crea un directorio remoto (MKD)
  rmdir <dir>                elimina un directorio remoto vacío (RMD)
  rm <archivo>               elimina un archivo remoto (DELE)
  mv <origen> <destino>      renombra o mueve un archivo (RNFR / RNTO)
  binary / ascii             cambia el modo de transferencia (TYPE I / TYPE A)
  syst                       muestra el sistema del servidor (SYST)
  noop                       envía señal de actividad (NOOP)
  raw <comando>              envía un comando FTP crudo al servidor
  lls / lpwd / lcd <dir>     comandos locales (listar, ver o cambiar carpeta local)
  ayuda                      muestra esta ayuda
  quit / exit                cierra la conexión (QUIT)"""


class ClienteFTP:
    def __init__(self, host, port=21, timeout=15):
        self.host = host
        self.port = port
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.rf = self.sock.makefile("rb")
        code, msg = self.leer_respuesta()
        print(msg)
        if not code.startswith("2"):
            raise ConnectionError(f"El servidor rechazó la conexión: {msg}")

    def leer_respuesta(self):
        """Lee una respuesta FTP (simple o multilínea) del canal de control."""
        lineas = []
        primera = self.rf.readline().decode("utf-8", errors="replace").rstrip("\r\n")
        if not primera:
            raise ConnectionError("El servidor cerró la conexión.")
        lineas.append(primera)
        codigo = primera[:3]
        # Si el 4to carácter es '-', la respuesta sigue hasta '<codigo> '
        if len(primera) >= 4 and primera[3] == "-":
            while True:
                ln = self.rf.readline().decode("utf-8", errors="replace").rstrip("\r\n")
                if not ln:
                    break
                lineas.append(ln)
                if ln.startswith(codigo + " "):
                    break
        return codigo, "\n".join(lineas)

    def enviar_cmd(self, cmd):
        """Envía un comando por el canal de control y devuelve (codigo, respuesta)."""
        self.sock.sendall((cmd + "\r\n").encode("utf-8"))
        return self.leer_respuesta()

    def login(self, user, password):
        code, msg = self.enviar_cmd(f"USER {user}")
        print(msg)
        if code == "331":
            code, msg = self.enviar_cmd(f"PASS {password}")
            print(msg)
        if not code.startswith("2"):
            raise PermissionError("Error de autenticación.")
        # Por defecto arrancamos en modo binario para no corromper archivos
        self.enviar_cmd("TYPE I")

    def abrir_datos_pasv(self):
        """Solicita modo pasivo (PASV) y abre el socket de datos."""
        code, msg = self.enviar_cmd("PASV")
        if code != "227":
            raise RuntimeError(f"No se pudo activar modo pasivo: {msg}")
        m = re.search(r"\((\d+),(\d+),(\d+),(\d+),(\d+),(\d+)\)", msg)
        if not m:
            raise RuntimeError(f"Respuesta PASV inválida: {msg}")
        nums = [int(x) for x in m.groups()]
        ip = ".".join(str(x) for x in nums[:4])
        puerto = nums[4] * 256 + nums[5]
        # Si el servidor devuelve una IP privada/0.0.0.0 detrás de NAT, usamos el host original
        if ip in ("0.0.0.0", "127.0.0.1") and self.host not in ("localhost", "127.0.0.1"):
            ip = self.host
        return socket.create_connection((ip, puerto), timeout=15)

    def listar(self, ruta=""):
        data_sock = self.abrir_datos_pasv()
        try:
            cmd = f"LIST {ruta}".strip()
            code, msg = self.enviar_cmd(cmd)
            print(msg)
            if not code.startswith(("1", "2")):
                return
            chunks = []
            while True:
                b = data_sock.recv(4096)
                if not b:
                    break
                chunks.append(b)
            salida = b"".join(chunks).decode("utf-8", errors="replace")
            if salida:
                print(salida.rstrip("\r\n"))
        finally:
            data_sock.close()
        _, fin = self.leer_respuesta()
        print(fin)

    def descargar(self, remoto, local=None):
        local = local or os.path.basename(remoto)
        data_sock = self.abrir_datos_pasv()
        total = 0
        try:
            code, msg = self.enviar_cmd(f"RETR {remoto}")
            print(msg)
            if not code.startswith(("1", "2")):
                return
            with open(local, "wb") as f:
                while True:
                    b = data_sock.recv(8192)
                    if not b:
                        break
                    f.write(b)
                    total += len(b)
        finally:
            data_sock.close()
        _, fin = self.leer_respuesta()
        print(fin)
        print(f"* Descargado '{remoto}' -> '{local}' ({total} bytes)")

    def subir(self, local, remoto=None):
        local = os.path.expanduser(local)
        if not os.path.isfile(local):
            print(f"! No existe el archivo local: {local}")
            return
        remoto = remoto or os.path.basename(local)
        data_sock = self.abrir_datos_pasv()
        total = 0
        try:
            code, msg = self.enviar_cmd(f"STOR {remoto}")
            print(msg)
            if not code.startswith(("1", "2")):
                return
            with open(local, "rb") as f:
                while True:
                    b = f.read(8192)
                    if not b:
                        break
                    data_sock.sendall(b)
                    total += len(b)
        finally:
            data_sock.close()
        _, fin = self.leer_respuesta()
        print(fin)
        print(f"* Subido '{local}' -> '{remoto}' ({total} bytes)")

    def renombrar(self, origen, destino):
        code, msg = self.enviar_cmd(f"RNFR {origen}")
        print(msg)
        if code.startswith("3"):
            _, msg2 = self.enviar_cmd(f"RNTO {destino}")
            print(msg2)

    def cerrar(self):
        try:
            _, msg = self.enviar_cmd("QUIT")
            print(msg)
        except OSError:
            pass
        finally:
            self.rf.close()
            self.sock.close()


def main():
    host = sys.argv[1] if len(sys.argv) > 1 else input("Host FTP [localhost]: ").strip() or "localhost"
    if len(sys.argv) > 2:
        port = int(sys.argv[2])
    else:
        p = input("Puerto [21]: ").strip()
        port = int(p) if p else 21

    try:
        ftp = ClienteFTP(host, port)
        user = input("Usuario [anonymous]: ").strip() or "anonymous"
        pw = getpass.getpass("Contraseña: ") if sys.stdin.isatty() else input("Contraseña: ")
        ftp.login(user, pw)
    except Exception as e:
        print(f"! {e}")
        sys.exit(1)

    print("* Conectado. Escribí 'ayuda' para ver los comandos.")

    try:
        while True:
            try:
                linea = input("ftp> ").strip()
            except EOFError:
                break
            if not linea:
                continue
            try:
                partes = shlex.split(linea)
            except ValueError as e:
                print(f"! Error de sintaxis: {e}")
                continue

            cmd = partes[0].lower()
            args = partes[1:]

            try:
                if cmd in ("quit", "exit", "bye"):
                    break
                elif cmd in ("ayuda", "help", "?"):
                    print(AYUDA)
                elif cmd in ("ls", "dir"):
                    ftp.listar(args[0] if args else "")
                elif cmd == "pwd":
                    print(ftp.enviar_cmd("PWD")[1])
                elif cmd == "cd":
                    if not args:
                        print("! Uso: cd <directorio>")
                    else:
                        print(ftp.enviar_cmd(f"CWD {args[0]}")[1])
                elif cmd == "cdup":
                    print(ftp.enviar_cmd("CDUP")[1])
                elif cmd == "get":
                    if not args:
                        print("! Uso: get <remoto> [local]")
                    else:
                        ftp.descargar(args[0], args[1] if len(args) > 1 else None)
                elif cmd == "put":
                    if not args:
                        print("! Uso: put <local> [remoto]")
                    else:
                        ftp.subir(args[0], args[1] if len(args) > 1 else None)
                elif cmd == "mkdir":
                    if not args:
                        print("! Uso: mkdir <directorio>")
                    else:
                        print(ftp.enviar_cmd(f"MKD {args[0]}")[1])
                elif cmd == "rmdir":
                    if not args:
                        print("! Uso: rmdir <directorio>")
                    else:
                        print(ftp.enviar_cmd(f"RMD {args[0]}")[1])
                elif cmd in ("rm", "del", "delete"):
                    if not args:
                        print("! Uso: rm <archivo>")
                    else:
                        print(ftp.enviar_cmd(f"DELE {args[0]}")[1])
                elif cmd in ("mv", "rename"):
                    if len(args) < 2:
                        print("! Uso: mv <origen> <destino>")
                    else:
                        ftp.renombrar(args[0], args[1])
                elif cmd == "binary":
                    print(ftp.enviar_cmd("TYPE I")[1])
                elif cmd == "ascii":
                    print(ftp.enviar_cmd("TYPE A")[1])
                elif cmd == "syst":
                    print(ftp.enviar_cmd("SYST")[1])
                elif cmd == "noop":
                    print(ftp.enviar_cmd("NOOP")[1])
                elif cmd == "raw":
                    if not args:
                        print("! Uso: raw <COMANDO FTP>")
                    else:
                        print(ftp.enviar_cmd(" ".join(args))[1])
                elif cmd == "lpwd":
                    print(os.getcwd())
                elif cmd == "lcd":
                    if not args:
                        print("! Uso: lcd <directorio>")
                    else:
                        os.chdir(os.path.expanduser(args[0]))
                        print(os.getcwd())
                elif cmd == "lls":
                    for item in sorted(os.listdir(".")):
                        print(item)
                else:
                    print("! Comando desconocido. Escribí 'ayuda'.")
            except Exception as e:
                print(f"! Error: {e}")
    except KeyboardInterrupt:
        print()
    finally:
        ftp.cerrar()


if __name__ == "__main__":
    main()