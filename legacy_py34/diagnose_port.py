# -*- coding: utf-8 -*-
"""Diagnostica por que uma porta serial nao abre, sem depender do pyserial.

Deliberadamente autocontido (so biblioteca padrao, nada de import de
outros arquivos do projeto) para poder ser colado direto num terminal
SSH de uma maquina sem internet, onde copiar o repositorio inteiro nao e
pratico.

Nao usar o pyserial aqui e proposital: separa uma falha no open() do
kernel (driver errado, porta ocupada, dispositivo sumido) de uma falha
na configuracao da porta pelo pyserial (termios, baudrate, paridade).
Sao causas diferentes com correcoes diferentes, e a mensagem do pyserial
sozinha nao distingue as duas.

Uso:
    python3 diagnose_port.py /dev/ttyUSB0
"""
import errno
import os
import stat
import sys


def secao(titulo):
    print("\n=== %s ===" % titulo)


def ler(caminho):
    """Le um arquivo de texto do /sys ou /proc, devolvendo None se falhar."""
    try:
        with open(caminho) as handle:
            return handle.read().strip()
    except (IOError, OSError):
        return None


def descreve_no(caminho):
    """Confere se o caminho existe e se e um dispositivo de caractere."""
    secao("1. O dispositivo existe?")
    try:
        info = os.stat(caminho)
    except OSError as exc:
        print("NAO. os.stat falhou: [Errno %d] %s" % (exc.errno, exc.strerror))
        if exc.errno == errno.ENOENT:
            print("  -> O conversor nao esta conectado, ou nenhum driver")
            print("     serial foi ligado a ele. Confira com 'lsusb' e")
            print("     'dmesg | tail -20'.")
        return False

    modo = info.st_mode
    tipo = "dispositivo de caractere" if stat.S_ISCHR(modo) else "NAO e dispositivo de caractere"
    print("Sim. %s, permissoes %s, uid=%d gid=%d, major=%d minor=%d" % (
        tipo, oct(stat.S_IMODE(modo)), info.st_uid, info.st_gid,
        os.major(info.st_rdev), os.minor(info.st_rdev)))
    if not stat.S_ISCHR(modo):
        print("  -> Um caminho que nao e dispositivo de caractere nunca vai")
        print("     funcionar como porta serial. Confira o caminho.")
        return False
    return True


def quem_esta_usando(caminho):
    """Varre /proc/*/fd procurando processos com a porta aberta."""
    secao("2. Algum processo esta segurando a porta?")
    encontrados = []
    for pid in os.listdir('/proc'):
        if not pid.isdigit():
            continue
        fd_dir = os.path.join('/proc', pid, 'fd')
        try:
            fds = os.listdir(fd_dir)
        except OSError:
            continue  # processo morreu, ou sem permissao (rode com sudo)
        for fd in fds:
            try:
                alvo = os.readlink(os.path.join(fd_dir, fd))
            except OSError:
                continue
            if alvo == caminho:
                cmd = ler(os.path.join('/proc', pid, 'cmdline')) or ''
                cmd = cmd.replace('\0', ' ').strip()
                encontrados.append((pid, cmd))

    if encontrados:
        for pid, cmd in encontrados:
            print("PID %s: %s" % (pid, cmd))
        print("  -> Finalize esses processos antes de abrir a porta:")
        print("     sudo kill %s" % ' '.join(p for p, _ in encontrados))
    else:
        print("Nenhum. (Se nao estiver rodando com sudo, processos de outros")
        print("usuarios nao aparecem aqui.)")
    return encontrados


def driver_ligado(caminho):
    """Descobre qual driver do kernel esta ligado a esta porta."""
    secao("3. Qual driver do kernel esta ligado?")
    nome = os.path.basename(caminho)
    base = "/sys/class/tty/%s/device" % nome

    try:
        driver = os.path.basename(os.readlink(base + "/driver"))
        print("Driver: %s" % driver)
    except OSError:
        print("Nao consegui ler %s/driver" % base)
        print("  -> A porta pode nao vir de um driver USB-serial.")
        return

    # Sobe ate o dispositivo USB para pegar VID:PID e nome do fabricante.
    for prefixo in ("../", "../../"):
        vid = ler(base + "/" + prefixo + "idVendor")
        pid = ler(base + "/" + prefixo + "idProduct")
        if vid and pid:
            fabricante = ler(base + "/" + prefixo + "manufacturer") or "?"
            produto = ler(base + "/" + prefixo + "product") or "?"
            print("Dispositivo USB: %s:%s (%s - %s)" % (vid, pid, fabricante, produto))
            break


def tenta_abrir(caminho):
    """Abre a porta no nivel do kernel, sem pyserial, e reporta o errno."""
    secao("4. O kernel deixa abrir? (open cru, sem pyserial)")
    flags = os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK
    try:
        fd = os.open(caminho, flags)
    except OSError as exc:
        print("NAO. [Errno %d] %s" % (exc.errno, exc.strerror))
        explica_errno(exc.errno)
        return False

    print("SIM, o open() do kernel funcionou.")
    try:
        tenta_configurar(fd, caminho)
    finally:
        os.close(fd)
    return True


def tenta_configurar(fd, caminho):
    """Se o open funcionou, testa a configuracao termios (o que o
    pyserial faz logo depois de abrir)."""
    secao("5. Da para configurar como serial? (termios)")
    try:
        import termios
    except ImportError:
        print("modulo termios indisponivel - pulando")
        return
    try:
        termios.tcgetattr(fd)
        print("SIM. A porta aceita configuracao serial normalmente.")
        print("  -> O kernel esta 100%. Se o app ainda falhar, o problema")
        print("     esta nos parametros usados (baudrate/paridade/stopbits)")
        print("     ou na versao do pyserial, nao no driver.")
    except termios.error as exc:
        args = exc.args
        codigo = args[0] if args else None
        texto = args[1] if len(args) > 1 else str(exc)
        print("NAO. termios falhou: [%s] %s" % (codigo, texto))
        explica_errno(codigo)


def explica_errno(codigo):
    dicas = {
        errno.EACCES: ("Permissao negada. Rode com sudo, ou adicione o usuario "
                       "ao grupo dono da porta:\n"
                       "     sudo usermod -aG dialout $USER   (depois deslogar e logar)"),
        errno.EBUSY: ("A porta esta ocupada por outro processo. Veja a secao 2 "
                      "acima, ou:\n     sudo fuser -v %s"),
        errno.ENOENT: ("O dispositivo sumiu. Conversor desconectado ou driver "
                       "descarregado."),
        errno.ENODEV: ("O dispositivo foi removido enquanto era acessado. "
                       "Cabo USB solto ou conversor resetando."),
        errno.EIO: ("Erro de I/O. O /dev existe mas o driver nao consegue "
                    "conversar com o chip - quase sempre driver errado\n"
                    "     (ex.: ftdi_sio forcado num chip que nao e FTDI). "
                    "Tente cp210x, pl2303 ou ch341."),
        errno.ENOTTY: ("O caminho nao e uma porta serial de verdade."),
        errno.EPERM: ("Operacao nao permitida mesmo com o arquivo acessivel."),
    }
    dica = dicas.get(codigo)
    if dica:
        print("  -> %s" % dica)
    else:
        print("  -> errno %s nao mapeado. Mande esta saida inteira para analise." % codigo)


def main():
    if len(sys.argv) != 2:
        print("Uso: python3 diagnose_port.py /dev/ttyUSB0")
        return 2
    caminho = sys.argv[1]

    print("Diagnostico de %s" % caminho)
    print("Rodando como uid=%d %s" % (
        os.geteuid(),
        "(root)" if os.geteuid() == 0 else "(SEM sudo - alguns testes ficam cegos)"))

    if not descreve_no(caminho):
        return 1
    quem_esta_usando(caminho)
    driver_ligado(caminho)
    tenta_abrir(caminho)

    print("\n=== FIM === Mande esta saida inteira.")
    return 0


if __name__ == '__main__':
    sys.exit(main())
