# -*- coding: utf-8 -*-
"""Substituto simples para 'socat pty pty' quando o socat nao esta
instalado (ex.: BeagleBone sem internet para instalar pacotes).

Cria dois pseudo-terminais e copia bytes de um para o outro nos dois
sentidos, imprimindo os caminhos (ex.: /dev/pts/3) para usar com
simulate_bus.py de um lado e bus_monitor.py do outro.

Uso:
    python3 legacy_py34/ptybridge.py
    (Ctrl+C para parar)
"""
import os
import pty
import select


def main():
    master_a, slave_a = pty.openpty()
    master_b, slave_b = pty.openpty()

    path_a = os.ttyname(slave_a)
    path_b = os.ttyname(slave_b)

    print("Ponte criada:")
    print("  lado A: %s" % path_a)
    print("  lado B: %s" % path_b)
    print("Use um caminho no simulate_bus.py e o outro no bus_monitor.py.")
    print("Ctrl+C para parar.")

    try:
        while True:
            readable, _, _ = select.select([master_a, master_b], [], [])
            if master_a in readable:
                data = os.read(master_a, 4096)
                if data:
                    os.write(master_b, data)
            if master_b in readable:
                data = os.read(master_b, 4096)
                if data:
                    os.write(master_a, data)
    except KeyboardInterrupt:
        print("Interrompido pelo usuario")
    finally:
        for fd in (master_a, slave_a, master_b, slave_b):
            try:
                os.close(fd)
            except OSError:
                pass


if __name__ == '__main__':
    main()
