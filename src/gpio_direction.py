"""Controle opcional do pino DE/RE de transceptores RS-485 (ex.: MAX485).

So e necessario se o hardware usado NAO tiver controle automatico de
direcao (auto RTS). Muitos adaptadores USB-RS485 e alguns modulos ja
cuidam disso sozinhos - nesse caso, nao use este modulo.

Requer a biblioteca Adafruit_BBIO (`pip install Adafruit_BBIO`), que so
funciona rodando diretamente na BeagleBone.
"""
from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Iterator

try:
    import Adafruit_BBIO.GPIO as GPIO
except ImportError:  # pragma: no cover - so existe na BeagleBone real
    GPIO = None


class RS485Direction:
    """Alterna o pino DE/RE entre modo transmissao (TX) e recepcao (RX).

    Exemplo de uso com o pino P9_12 ligado a DE e RE (unidos) do MAX485:

        direction = RS485Direction(pin="P9_12")
        with direction.transmitting():
            serial_port.write(frame)
        # ao sair do bloco, volta automaticamente para modo recepcao
    """

    def __init__(self, pin: str, active_high: bool = True, switch_delay: float = 0.0005):
        if GPIO is None:
            raise RuntimeError(
                "Adafruit_BBIO nao esta disponivel. Instale com "
                "'pip install Adafruit_BBIO' e execute na BeagleBone."
            )
        self.pin = pin
        self.active_high = active_high
        self.switch_delay = switch_delay
        GPIO.setup(self.pin, GPIO.OUT)
        self.set_receive()

    def _write(self, level_high: bool) -> None:
        level = GPIO.HIGH if level_high else GPIO.LOW
        GPIO.output(self.pin, level)

    def set_transmit(self) -> None:
        self._write(self.active_high)
        time.sleep(self.switch_delay)

    def set_receive(self) -> None:
        self._write(not self.active_high)
        time.sleep(self.switch_delay)

    @contextmanager
    def transmitting(self) -> Iterator[None]:
        self.set_transmit()
        try:
            yield
        finally:
            self.set_receive()
