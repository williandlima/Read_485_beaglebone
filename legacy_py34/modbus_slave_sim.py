# -*- coding: utf-8 -*-
"""Simula um escravo Modbus RTU real, respondendo a consultas.

Ao contrario de simulate_bus.py (que so blasta frames sem serem pedidos,
para testar bus_monitor.py num par de ptys locais), este script se
comporta como um dispositivo Modbus RTU de verdade: fica ouvindo o
barramento serial, e quando recebe uma requisicao valida (CRC correto,
endereco de escravo igual ao seu) responde de acordo com a funcao
pedida.

Serve para testar toda a cadeia (conversor USB-RS485 + driver + pyserial
+ bus_monitor.py / scripts de consulta) sobre um barramento RS-485 de
verdade, sem precisar de um equipamento industrial real -- ideal numa
bancada com dois conversores na mesma linha A/B: um roda este
simulador, o outro roda o cliente (o app da BeagleBone).

Suporta a funcao 0x03 (Read Holding Registers) sobre um pequeno banco
de registradores em memoria. O registrador 1 alterna de valor
periodicamente, para poder testar o destaque MUDOU do bus_monitor.py.

Uso (no lado que faz o papel do "equipamento"):
    python modbus_slave_sim.py COM8 --slave 1 --baudrate 9600
    python3 modbus_slave_sim.py /dev/ttyUSB0 --slave 1 --baudrate 9600

E do outro conversor, na BeagleBone, consultando (ou so escutando com
o bus_monitor.py):
    python3 legacy_py34/bus_monitor.py /dev/ttyUSB0 --baudrate 9600
"""
import argparse
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


def montar_frame(slave_id, function_code, payload):
    corpo = bytearray([slave_id, function_code]) + bytearray(payload)
    crc = crc16_modbus(bytes(corpo))
    corpo.append(crc & 0xFF)
    corpo.append((crc >> 8) & 0xFF)
    return bytes(corpo)


def resposta_read_holding(slave_id, valores):
    payload = bytearray([len(valores) * 2])
    for v in valores:
        payload.append((v >> 8) & 0xFF)
        payload.append(v & 0xFF)
    return montar_frame(slave_id, 0x03, payload)


def silencio_entre_frames(baudrate, parity):
    """Tempo minimo sem bytes novos para considerar um frame RTU encerrado."""
    parity_bits = 0 if parity.upper() == 'N' else 1
    bits_por_char = 1 + 8 + parity_bits + 1  # start + 8 dados + paridade + stop
    tempo_char = bits_por_char / float(baudrate)
    return max(tempo_char * 3.5, 0.005)


def ler_frame(ser, silencio):
    """Le um frame delimitado por silencio no barramento (padrao Modbus RTU).

    Devolve os bytes do frame, ou b'' se nada chegou (permite ao chamador
    continuar rodando sua propria logica periodica entre uma leitura e
    outra, em vez de bloquear indefinidamente)."""
    buffer = bytearray()
    ultimo = None
    while True:
        chunk = ser.read(64)
        agora = time.time()
        if chunk:
            buffer.extend(chunk)
            ultimo = agora
        elif buffer and ultimo is not None and (agora - ultimo) >= silencio:
            return bytes(buffer)
        elif not buffer:
            return b''


def main():
    p = argparse.ArgumentParser(
        description="Simula um escravo Modbus RTU que responde a consultas reais.")
    p.add_argument('port', help="Porta serial, ex.: COM8 ou /dev/ttyUSB0")
    p.add_argument('--slave', type=int, default=1,
                    help="Endereco do escravo simulado (default: 1)")
    p.add_argument('--baudrate', type=int, default=9600)
    p.add_argument('--parity', default='N', choices=['N', 'E', 'O'])
    p.add_argument('--change-every', type=float, default=5.0,
                    help="Segundos entre mudancas do registrador 1 (default: 5)")
    args = p.parse_args()

    ser = serial.Serial(args.port, args.baudrate, parity=args.parity, timeout=0.05)
    silencio = silencio_entre_frames(args.baudrate, args.parity)

    # Banco de registradores simulado: registrador 0 fixo, registrador 1 alterna.
    registradores = {0: 123, 1: 0}
    proxima_mudanca = time.time() + args.change_every

    print("Simulando escravo Modbus RTU id={} em {} @ {} bps, paridade {}".format(
        args.slave, args.port, args.baudrate, args.parity))
    print("Registrador 0 = 123 (fixo), registrador 1 alterna a cada {}s".format(
        args.change_every))
    print("So suporta a funcao 0x03 (Read Holding Registers). Ctrl+C para parar.\n")

    try:
        while True:
            if time.time() >= proxima_mudanca:
                registradores[1] = 1 - registradores[1]
                proxima_mudanca = time.time() + args.change_every
                print("-> registrador 1 mudou para {}".format(registradores[1]))

            frame = ler_frame(ser, silencio)
            if len(frame) < 4:
                continue

            crc_recebido = frame[-2] | (frame[-1] << 8)
            if crc16_modbus(frame[:-2]) != crc_recebido:
                continue  # CRC invalido: ruido, colisao, ou frame de outro escravo

            slave_id = frame[0]
            if slave_id != args.slave:
                continue  # nao e pra mim

            function_code = frame[1]
            if function_code != 0x03 or len(frame) != 8:
                print("ignorando funcao/tamanho nao suportado: {}".format(
                    ' '.join('{:02x}'.format(b) for b in bytearray(frame))))
                continue

            addr = (frame[2] << 8) | frame[3]
            qtd = (frame[4] << 8) | frame[5]

            valores = [registradores.get(addr + i, 0) for i in range(qtd)]
            resposta = resposta_read_holding(slave_id, valores)
            ser.write(resposta)
            print("respondi a leitura addr={} qtd={}: {}".format(addr, qtd, valores))
    except KeyboardInterrupt:
        print("\nEncerrado pelo usuario.")
    finally:
        ser.close()


if __name__ == '__main__':
    main()
