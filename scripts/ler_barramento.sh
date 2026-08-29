#!/usr/bin/env bash
# Lancador do monitor de barramento RS-485 na BeagleBone.
#
# Junta num comando so o que hoje precisa de varios passos manuais:
# achar a porta serial, garantir que o driver do conversor esta ligado,
# apontar o PYTHONPATH para o pyserial vendorizado, e rodar
# bus_monitor.py com os parametros certos.
#
# Uso:
#   ./scripts/ler_barramento.sh                       # autodetecta porta, 9600 N
#   ./scripts/ler_barramento.sh --baudrate 19200
#   ./scripts/ler_barramento.sh --parity E --log eventos.log
#   ./scripts/ler_barramento.sh /dev/ttyUSB1 --baudrate 38400
#
# Qualquer argumento extra e repassado direto para bus_monitor.py.

set -euo pipefail

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$RAIZ"

VID="0856"
PID="ac15"

# Primeiro argumento posicional (nao comecando com -) e tratado como a
# porta; os demais vao direto para o bus_monitor.py.
PORTA=""
ARGS=()
for arg in "$@"; do
    if [[ -z "$PORTA" && "$arg" != -* ]]; then
        PORTA="$arg"
    else
        ARGS+=("$arg")
    fi
done

if [[ -z "$PORTA" ]]; then
    # Autodetecta: primeira /dev/ttyUSB* que existir.
    for candidata in /dev/ttyUSB*; do
        if [[ -e "$candidata" ]]; then
            PORTA="$candidata"
            break
        fi
    done
fi

if [[ -z "$PORTA" || ! -e "$PORTA" ]]; then
    echo "Nenhuma /dev/ttyUSB* encontrada. Tentando ligar o driver do conversor..."
    if [[ -x "$RAIZ/scripts/setup_rs485_usb.sh" ]]; then
        sudo "$RAIZ/scripts/setup_rs485_usb.sh" "$VID" "$PID" || true
    fi
    for candidata in /dev/ttyUSB*; do
        if [[ -e "$candidata" ]]; then
            PORTA="$candidata"
            break
        fi
    done
fi

if [[ -z "$PORTA" || ! -e "$PORTA" ]]; then
    echo "Ainda sem porta serial disponivel."
    echo "Confira: lsusb  (o conversor aparece?)"
    echo "         dmesg | tail -20  (o kernel reconheceu o dispositivo?)"
    exit 1
fi

echo "Usando porta: $PORTA"
exec env PYTHONPATH="$RAIZ" python3 "$RAIZ/legacy_py34/bus_monitor.py" "$PORTA" "${ARGS[@]}"
