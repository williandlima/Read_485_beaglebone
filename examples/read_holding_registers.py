"""Exemplo minimo: le N holding registers de um escravo Modbus RTU
conhecido, sem depender de arquivo de configuracao.

Uso:
    python examples/read_holding_registers.py /dev/ttyO4 --slave 1 \\
        --address 0 --count 10 --baudrate 9600
"""
from __future__ import annotations

import argparse

from pymodbus.client import ModbusSerialClient


def main() -> None:
    parser = argparse.ArgumentParser(description="Le holding registers via Modbus RTU/RS-485")
    parser.add_argument("port", help="Porta serial, ex.: /dev/ttyO4")
    parser.add_argument("--slave", type=int, default=1, help="ID do escravo Modbus")
    parser.add_argument("--address", type=int, default=0, help="Endereco inicial")
    parser.add_argument("--count", type=int, default=10, help="Quantidade de registradores")
    parser.add_argument("--baudrate", type=int, default=9600)
    parser.add_argument("--parity", default="N", choices=["N", "E", "O"])
    parser.add_argument("--stopbits", type=int, default=1)
    args = parser.parse_args()

    client = ModbusSerialClient(
        port=args.port,
        baudrate=args.baudrate,
        parity=args.parity,
        stopbits=args.stopbits,
        timeout=1.0,
    )

    if not client.connect():
        raise SystemExit(f"Nao foi possivel abrir a porta {args.port}")

    try:
        response = client.read_holding_registers(
            address=args.address, count=args.count, slave=args.slave
        )
        if response.isError():
            raise SystemExit(f"Erro Modbus: {response}")
        print(f"Registradores [{args.address}:{args.address + args.count}] = {response.registers}")
    finally:
        client.close()


if __name__ == "__main__":
    main()
