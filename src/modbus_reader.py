"""Leitor Modbus RTU (mestre) via RS-485 para BeagleBone.

Le registradores de um escravo Modbus conhecido, usando pymodbus sobre
a porta serial RS-485. Para trafego de dispositivos ainda nao mapeados,
veja `rs485_sniffer.py`.
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path
from typing import Any, Optional

import yaml
from pymodbus.client import ModbusSerialClient
from pymodbus.exceptions import ModbusException

logger = logging.getLogger("modbus_reader")

REGISTER_READERS = {
    "holding": "read_holding_registers",
    "input": "read_input_registers",
    "coils": "read_coils",
    "discrete": "read_discrete_inputs",
}


def load_config(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def build_client(serial_cfg: dict[str, Any]) -> ModbusSerialClient:
    return ModbusSerialClient(
        port=serial_cfg["port"],
        baudrate=serial_cfg.get("baudrate", 9600),
        bytesize=serial_cfg.get("bytesize", 8),
        parity=serial_cfg.get("parity", "N"),
        stopbits=serial_cfg.get("stopbits", 1),
        timeout=serial_cfg.get("timeout", 1.0),
    )


def read_once(client: ModbusSerialClient, modbus_cfg: dict[str, Any]) -> Optional[list[int]]:
    reader_name = REGISTER_READERS.get(modbus_cfg.get("register_type", "holding"))
    if reader_name is None:
        raise ValueError(f"register_type invalido: {modbus_cfg.get('register_type')}")

    reader = getattr(client, reader_name)
    try:
        response = reader(
            address=modbus_cfg["start_address"],
            count=modbus_cfg["count"],
            slave=modbus_cfg["slave_id"],
        )
    except ModbusException as exc:
        logger.error("Erro de comunicacao Modbus: %s", exc)
        return None

    if response.isError():
        logger.error("Escravo retornou erro: %s", response)
        return None

    if hasattr(response, "registers"):
        return response.registers
    if hasattr(response, "bits"):
        return response.bits
    return None


def run(config_path: str, continuous: bool) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = load_config(config_path)

    dir_cfg = cfg.get("direction_gpio", {})
    if dir_cfg.get("enabled"):
        # O pymodbus nao expoe um hook em torno de cada escrita/leitura
        # serial, entao nao ha como sincronizar o toggle manual do pino
        # DE/RE com o timing interno do client. Este modo requer um
        # transceptor/adaptador com controle automatico de direcao
        # (auto RTS), ou suporte RS-485 a nivel de kernel/UART.
        # RS485Direction (gpio_direction.py) fica disponivel para uso em
        # codigo Modbus RTU de baixo nivel escrito a mao (veja
        # frame_parser.build_request), fora do fluxo do pymodbus.
        logger.error(
            "direction_gpio manual nao e suportado com modbus_reader.py "
            "(pymodbus). Use um transceptor com auto RTS ou escreva um "
            "master de baixo nivel usando src/frame_parser.py."
        )
        return 1

    client = build_client(cfg["serial"])
    if not client.connect():
        logger.error("Nao foi possivel abrir a porta serial %s", cfg["serial"]["port"])
        return 1

    logger.info(
        "Conectado em %s @ %s bps (slave=%s, %s[%s:%s])",
        cfg["serial"]["port"],
        cfg["serial"].get("baudrate", 9600),
        cfg["modbus"]["slave_id"],
        cfg["modbus"].get("register_type", "holding"),
        cfg["modbus"]["start_address"],
        cfg["modbus"]["count"],
    )

    try:
        while True:
            values = read_once(client, cfg["modbus"])
            if values is not None:
                logger.info("Valores lidos: %s", values)
            if not continuous:
                break
            time.sleep(cfg["modbus"].get("poll_interval", 1.0))
    except KeyboardInterrupt:
        logger.info("Interrompido pelo usuario")
    finally:
        client.close()

    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Leitor Modbus RTU via RS-485 (BeagleBone)")
    parser.add_argument(
        "--config",
        default=str(Path(__file__).resolve().parent.parent / "config" / "config.yaml"),
        help="Caminho para o arquivo config.yaml",
    )
    parser.add_argument(
        "--continuous", action="store_true", help="Fica lendo em loop, respeitando poll_interval"
    )
    args = parser.parse_args()
    sys.exit(run(args.config, args.continuous))


if __name__ == "__main__":
    main()
