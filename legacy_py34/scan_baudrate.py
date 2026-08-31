# -*- coding: utf-8 -*-
"""Descobre automaticamente o baudrate/paridade do barramento RS-485.

Testa uma lista de combinacoes comuns (baudrate x paridade), escutando
o barramento por alguns segundos em cada uma, e conta quantos quadros
com CRC valido apareceram. A combinacao certa deve mostrar varios
quadros validos; as erradas normalmente mostram zero (ou lixo com CRC
invalido). Nao escreve nada no barramento, so escuta.

Uso:
    python3 scan_baudrate.py /dev/ttyUSB0
    python3 scan_baudrate.py /dev/ttyUSB0 --duration 3
"""
import argparse
import sys
import time

import serial

from portdiag import (OPEN_ERRORS, describe_open_error, read_timeout_for,
                      report_open_error)

CANDIDATE_BAUDRATES = [9600, 19200, 38400, 57600, 115200]
CANDIDATE_PARITIES = ['N', 'E', 'O']


def crc16_modbus(data):
    crc = 0xFFFF
    for byte in bytearray(data):
        crc ^= byte
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc & 0xFFFF


def parse_frame(data):
    if len(data) < 4:
        return None
    crc_received = data[-2] | (data[-1] << 8)
    crc_calculated = crc16_modbus(data[:-2])
    return crc_received == crc_calculated


def char_time_seconds(baudrate, bytesize=8, parity='N', stopbits=1):
    parity_bits = 0 if parity.upper() == 'N' else 1
    bits_per_char = 1 + bytesize + parity_bits + stopbits
    return float(bits_per_char) / baudrate


def scan_one(port, baudrate, parity, duration):
    """Escuta o barramento por 'duration' segundos nesta configuracao.

    Retorna (validos, invalidos, None) em caso de sucesso, ou
    (0, 0, mensagem_de_erro) se nao deu para abrir a porta."""
    silence = max(char_time_seconds(baudrate, 8, parity, 1) * 3.5, 0.005)
    try:
        ser = serial.Serial(port, baudrate, parity=parity, stopbits=1,
                            timeout=read_timeout_for(silence))
    except OPEN_ERRORS as exc:
        return (0, 0, describe_open_error(exc)[0])

    buffer = bytearray()
    last_byte_time = None
    valid = 0
    invalid = 0

    start = time.time()
    while time.time() - start < duration:
        chunk = ser.read(256)
        now = time.time()
        if chunk:
            buffer.extend(chunk)
            last_byte_time = now
        elif buffer and last_byte_time is not None and (now - last_byte_time) >= silence:
            crc_ok = parse_frame(bytes(buffer))
            if crc_ok is True:
                valid += 1
            elif crc_ok is False:
                invalid += 1
            buffer = bytearray()
            last_byte_time = None

    ser.close()
    return (valid, invalid, None)


def main():
    parser = argparse.ArgumentParser(
        description="Descobre o baudrate/paridade do barramento RS-485 por tentativa")
    parser.add_argument('port', help="Porta serial, ex.: /dev/ttyUSB0")
    parser.add_argument('--duration', type=float, default=2.0,
                         help="Segundos escutando em cada combinacao (default 2.0)")
    args = parser.parse_args()

    # Antes de varrer 15 combinacoes, confirma que da para abrir a porta.
    # Se nao der, o motivo e sempre o mesmo nas 15 - melhor mostrar a causa
    # real uma vez do que repetir "ERRO ao abrir a porta" sem explicacao.
    try:
        probe = serial.Serial(args.port, 9600, timeout=0.1)
    except OPEN_ERRORS as exc:
        report_open_error(sys.stderr.write, args.port, exc)
        return 1
    probe.close()

    combos = [(b, p) for b in CANDIDATE_BAUDRATES for p in CANDIDATE_PARITIES]
    total = len(combos)
    results = []

    print("Escutando %s por %.1fs em cada uma de %d combinacoes "
          "(total ~%.0fs). Precisa ter trafego real no barramento "
          "durante o teste.\n" % (args.port, args.duration, total,
                                   total * args.duration))

    for i, (baudrate, parity) in enumerate(combos, 1):
        print("[%d/%d] %d bps, paridade %s ... " % (i, total, baudrate, parity), end='')
        valid, invalid, error = scan_one(args.port, baudrate, parity, args.duration)
        if error is not None:
            print("ERRO ao abrir a porta: %s" % error)
            continue
        print("%d quadros validos, %d invalidos" % (valid, invalid))
        results.append((baudrate, parity, valid, invalid))

    results.sort(key=lambda r: r[2], reverse=True)

    print("\n=== RESULTADO (ordenado por quadros validos) ===")
    for baudrate, parity, valid, invalid in results:
        marker = "  <-- provavel candidato" if valid > 0 else ""
        print("%6d bps  paridade %s   validos=%-4d invalidos=%-4d%s" %
              (baudrate, parity, valid, invalid, marker))

    if not results or results[0][2] == 0:
        print("\nNenhuma combinacao encontrou quadros com CRC valido. "
              "Confirme se ha trafego real no barramento agora, se A/B "
              "nao estao invertidos, e se a porta esta certa.")


if __name__ == '__main__':
    sys.exit(main() or 0)
