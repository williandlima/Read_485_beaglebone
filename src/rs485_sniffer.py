"""Sniffer passivo de barramento RS-485 para engenharia reversa.

Escuta a porta serial continuamente, separa os bytes recebidos em
quadros usando o criterio de silencio entre quadros do Modbus RTU
(~3.5 tempos de caractere) e tenta decodificar cada quadro como Modbus
RTU (endereco, funcao, payload, CRC). Util quando se desconhece o
protocolo exato falado no barramento (dispositivo nao documentado,
protocolo proprietario semelhante a Modbus, etc.).

Nao transmite nada no barramento - apenas escuta.
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path
from typing import Any, Iterator

import serial
import yaml

from src.frame_parser import parse_frame

logger = logging.getLogger("rs485_sniffer")


def char_time_seconds(baudrate: int, bytesize: int, parity: str, stopbits: int) -> float:
    """Tempo para transmitir um caractere serial (start+dados+paridade+stop)."""
    parity_bits = 0 if parity.upper() == "N" else 1
    bits_per_char = 1 + bytesize + parity_bits + stopbits  # start + dados + paridade + stop
    return bits_per_char / baudrate


def read_frames(
    ser: serial.Serial, silence_seconds: float, chunk_size: int = 256
) -> Iterator[bytes]:
    """Le da porta serial e produz (yield) blocos de bytes separados por
    periodos de silencio maiores que `silence_seconds`.
    """
    buffer = bytearray()
    last_byte_time = None

    while True:
        chunk = ser.read(chunk_size)
        now = time.monotonic()

        if chunk:
            buffer.extend(chunk)
            last_byte_time = now
            continue

        if buffer and last_byte_time is not None:
            idle = now - last_byte_time
            if idle >= silence_seconds:
                yield bytes(buffer)
                buffer.clear()
                last_byte_time = None


def run(config_path: str) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    with open(config_path, "r", encoding="utf-8") as f:
        cfg: dict[str, Any] = yaml.safe_load(f)

    serial_cfg = cfg["serial"]
    sniffer_cfg = cfg.get("sniffer", {})

    ser = serial.Serial(
        port=serial_cfg["port"],
        baudrate=serial_cfg.get("baudrate", 9600),
        bytesize=serial_cfg.get("bytesize", 8),
        parity=serial_cfg.get("parity", "N"),
        stopbits=serial_cfg.get("stopbits", 1),
        timeout=0.01,
    )

    silence = max(
        char_time_seconds(
            serial_cfg.get("baudrate", 9600),
            serial_cfg.get("bytesize", 8),
            serial_cfg.get("parity", "N"),
            serial_cfg.get("stopbits", 1),
        )
        * sniffer_cfg.get("inter_frame_silence_multiplier", 3.5),
        sniffer_cfg.get("min_silence_seconds", 0.005),
    )

    logger.info(
        "Escutando %s @ %s bps (silencio entre quadros: %.4f s). Ctrl+C para sair.",
        serial_cfg["port"],
        serial_cfg.get("baudrate", 9600),
        silence,
    )

    try:
        for raw in read_frames(ser, silence):
            frame = parse_frame(raw)
            if frame is None:
                logger.warning("Bloco curto demais para ser um quadro: %s", raw.hex(" "))
                continue
            logger.info(str(frame))
    except KeyboardInterrupt:
        logger.info("Interrompido pelo usuario")
    finally:
        ser.close()

    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Sniffer passivo de RS-485 para engenharia reversa (BeagleBone)"
    )
    parser.add_argument(
        "--config",
        default=str(Path(__file__).resolve().parent.parent / "config" / "config.yaml"),
        help="Caminho para o arquivo config.yaml",
    )
    args = parser.parse_args()
    sys.exit(run(args.config))


if __name__ == "__main__":
    main()
