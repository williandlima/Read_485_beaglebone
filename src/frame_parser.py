"""Utilitarios para calculo de CRC16 e decodificacao de quadros Modbus RTU.

Usado tanto pelo leitor ativo (mestre Modbus) quanto pelo sniffer passivo,
para inspecionar o trafego bruto do barramento RS-485 durante engenharia
reversa de dispositivos desconhecidos.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

FUNCTION_NAMES = {
    0x01: "Read Coils",
    0x02: "Read Discrete Inputs",
    0x03: "Read Holding Registers",
    0x04: "Read Input Registers",
    0x05: "Write Single Coil",
    0x06: "Write Single Register",
    0x0F: "Write Multiple Coils",
    0x10: "Write Multiple Registers",
    0x16: "Mask Write Register",
    0x17: "Read/Write Multiple Registers",
}


def crc16_modbus(data: bytes) -> int:
    """Calcula o CRC16 (poly 0xA001, init 0xFFFF) usado pelo Modbus RTU."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc & 0xFFFF


@dataclass
class ModbusFrame:
    raw: bytes
    slave_id: int
    function_code: int
    payload: bytes
    crc_received: int
    crc_calculated: int
    is_exception: bool = False

    @property
    def crc_ok(self) -> bool:
        return self.crc_received == self.crc_calculated

    @property
    def function_name(self) -> str:
        code = self.function_code & 0x7F
        return FUNCTION_NAMES.get(code, f"Desconhecida (0x{code:02X})")

    def __str__(self) -> str:
        status = "OK" if self.crc_ok else "CRC INVALIDO"
        kind = " [EXCECAO]" if self.is_exception else ""
        return (
            f"Slave={self.slave_id:3d} FC=0x{self.function_code:02X} "
            f"({self.function_name}){kind} "
            f"Payload={self.payload.hex(' ')} CRC={status} "
            f"raw={self.raw.hex(' ')}"
        )


def parse_frame(data: bytes) -> Optional[ModbusFrame]:
    """Tenta decodificar `data` como um unico quadro Modbus RTU.

    Retorna None se o quadro for curto demais para ser valido (< 4 bytes:
    endereco + funcao + CRC). Nao valida o tamanho do payload conforme a
    funcao, pois o objetivo aqui e apoiar engenharia reversa de trafego
    ainda nao mapeado.
    """
    if len(data) < 4:
        return None

    slave_id = data[0]
    function_code = data[1]
    payload = data[2:-2]
    crc_received = data[-2] | (data[-1] << 8)
    crc_calculated = crc16_modbus(data[:-2])
    is_exception = bool(function_code & 0x80)

    return ModbusFrame(
        raw=data,
        slave_id=slave_id,
        function_code=function_code,
        payload=payload,
        crc_received=crc_received,
        crc_calculated=crc_calculated,
        is_exception=is_exception,
    )


def build_request(slave_id: int, function_code: int, payload: bytes) -> bytes:
    """Monta um quadro Modbus RTU completo (com CRC) a partir dos campos."""
    body = bytes([slave_id, function_code]) + payload
    crc = crc16_modbus(body)
    return body + bytes([crc & 0xFF, (crc >> 8) & 0xFF])
