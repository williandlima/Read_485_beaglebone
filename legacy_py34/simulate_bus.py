# -*- coding: utf-8 -*-
"""Gerador de trafego Modbus RTU falso para testar bus_monitor.py sem
hardware real.

Escreve quadros validos (CRC correto) em uma porta serial, simulando
alguns escravos fixos e, periodicamente, uma "chave" que muda de estado
(equivalente a um payload diferente na mesma combinacao slave/funcao) -
o cenario que dispara o destaque MUDOU no monitor.

Uso tipico (dois terminais):
    socat -d -d pty,raw,echo=0,link=/tmp/ttyBUS_A pty,raw,echo=0,link=/tmp/ttyBUS_B
    python3 legacy_py34/simulate_bus.py /tmp/ttyBUS_A --baudrate 9600
    python3 legacy_py34/bus_monitor.py /tmp/ttyBUS_B --baudrate 9600
"""
import argparse
import random
import time

import serial


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


def build_frame(slave_id, function_code, payload):
    body = bytearray([slave_id, function_code]) + bytearray(payload)
    crc = crc16_modbus(bytes(body))
    body.append(crc & 0xFF)
    body.append((crc >> 8) & 0xFF)
    return bytes(body)


def holding_registers_response(slave_id, values):
    payload = bytearray([len(values) * 2])
    for v in values:
        payload.append((v >> 8) & 0xFF)
        payload.append(v & 0xFF)
    return build_frame(slave_id, 0x03, payload)


def main():
    parser = argparse.ArgumentParser(
        description="Simula trafego Modbus RTU em uma porta serial (teste local)")
    parser.add_argument('port', help="Porta serial de saida, ex.: /tmp/ttyBUS_A")
    parser.add_argument('--baudrate', type=int, default=9600)
    parser.add_argument('--interval', type=float, default=1.0,
                         help="Segundos entre quadros (default 1.0)")
    parser.add_argument('--switch-every', type=int, default=5,
                         help="A cada N quadros do escravo 2, alterna o "
                              "estado da 'chave' simulada (default 5)")
    args = parser.parse_args()

    ser = serial.Serial(args.port, args.baudrate, timeout=1.0)

    switch_state = 0
    count = 0

    print("Simulando trafego em %s @ %s bps (Ctrl+C para parar)" %
          (args.port, args.baudrate))

    try:
        while True:
            # Escravo 1: valores estaveis (ex.: sensor de temperatura)
            temp = 200 + random.randint(-2, 2)
            frame = holding_registers_response(1, [temp, 50])
            ser.write(frame)
            time.sleep(args.interval)

            # Escravo 2: contem a "chave" que muda de estado de tempos
            # em tempos, simulando o cenario descrito pelo usuario.
            count += 1
            if count % args.switch_every == 0:
                switch_state = 1 - switch_state
                print("-> chave mudou de estado: %d" % switch_state)
            frame = holding_registers_response(2, [switch_state, 0])
            ser.write(frame)
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("Interrompido pelo usuario")
    finally:
        ser.close()


if __name__ == '__main__':
    main()
