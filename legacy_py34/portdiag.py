# -*- coding: utf-8 -*-
"""Diagnostico de falhas ao abrir a porta serial.

Quando o open() da porta falha, o motivo real (o errno do sistema) e a
unica informacao que interessa: permissao, porta ocupada, dispositivo
sumido ou driver errado dao erros diferentes e exigem correcoes
diferentes. Este modulo traduz esse errno para uma dica acionavel.

Compativel com Python 3.4 (sem f-strings).
"""
import errno

import serial

try:
    import termios
    # termios.error NAO herda de OSError nesta versao do Python, entao
    # precisa estar explicitamente na tupla de excecoes capturadas.
    OPEN_ERRORS = (serial.SerialException, OSError, termios.error)
except ImportError:
    OPEN_ERRORS = (serial.SerialException, OSError)


def read_timeout_for(silence):
    """Timeout de leitura que permite enxergar o silencio entre quadros.

    ser.read(n) do pyserial so retorna quando junta n bytes ou quando
    estoura o timeout. Se esse timeout for maior que o silencio de 3.5
    tempos de caractere que separa dois quadros Modbus RTU, o intervalo
    acontece DENTRO da leitura e nunca e observado: os quadros chegam
    grudados num buffer so e o CRC do conjunto da invalido. Mantendo o
    timeout na metade do silencio, o intervalo sempre cai entre duas
    leituras e a separacao de quadros funciona.
    """
    return max(silence / 2.0, 0.0002)


def describe_open_error(exc):
    """Retorna (mensagem_real, dica) para uma falha ao abrir a porta.

    O pyserial embrulha o erro do sistema, entao o errno as vezes vem no
    atributo .errno e as vezes so no texto ("[Errno 5] ..."). Olhamos os
    dois para conseguir dar uma dica util.
    """
    text = str(exc)
    code = getattr(exc, 'errno', None)

    def matches(errno_code, *needles):
        if code == errno_code:
            return True
        lowered = text.lower()
        for needle in needles:
            if needle.lower() in lowered:
                return True
        return False

    if matches(errno.EACCES, 'permission denied'):
        hint = ("Permissao. Rode com sudo, ou adicione o usuario ao grupo "
                "dialout: sudo usermod -aG dialout $USER (precisa deslogar "
                "e logar de novo).")
    elif matches(errno.EBUSY, 'device or resource busy'):
        hint = ("A porta esta ocupada por outro processo. Descubra qual com: "
                "sudo fuser -v /dev/ttyUSB0   e finalize-o.")
    elif matches(errno.ENOENT, 'no such file'):
        hint = ("O dispositivo sumiu (conversor desconectado, ou o driver foi "
                "descarregado). Confira: ls -l /dev/ttyUSB* e dmesg | tail")
    elif matches(errno.ENOTTY, 'inappropriate ioctl for device'):
        hint = ("O arquivo existe e abriu, mas nao e um dispositivo serial de "
                "verdade (o kernel recusou a configuracao de baudrate). "
                "Confirme que o caminho e mesmo a porta do conversor - "
                "'ls -l' deve mostrar um 'c' no inicio (dispositivo de "
                "caractere), como em: crw-rw---- 1 root dialout 188, 0 "
                "/dev/ttyUSB0")
    elif matches(errno.EIO, 'input/output error'):
        hint = ("Erro de I/O ja no open(). Quase sempre significa que o driver "
                "serial ligado ao conversor nao e o certo para o chip dele - "
                "por exemplo ftdi_sio forcado via new_id em um chip que nao e "
                "FTDI. O /dev/ttyUSB0 aparece, mas o driver nao consegue "
                "conversar com o chip. Tente outro driver (cp210x, pl2303, "
                "ch341) da mesma forma que fez com o ftdi_sio.")
    else:
        hint = None
    return text, hint


def report_open_error(write, port, exc):
    """Escreve o diagnostico completo usando a funcao 'write' dada
    (ex.: print-like ou sys.stderr.write com \\n embutido)."""
    text, hint = describe_open_error(exc)
    write("Nao consegui abrir %s\n" % port)
    write("  erro do sistema: %s\n" % text)
    if hint is not None:
        write("  causa provavel: %s\n" % hint)
    else:
        write("  (errno nao reconhecido - mande essa linha inteira "
              "para analise)\n")
