#!/usr/bin/env bash
# Habilita uma UART da BeagleBone Black para uso com RS-485 via config-pin.
#
# Uso: ./setup_uart.sh <numero_uart> <pino_tx> <pino_rx>
# Exemplo (UART4, pinos padrao P9_13/P9_11):
#   ./setup_uart.sh 4 P9_13 P9_11
#
# Mapeamento comum de UARTs na BeagleBone Black (verifique o pinout da
# sua revisao de placa antes de usar):
#   UART1 -> TX=P9_24 RX=P9_26
#   UART2 -> TX=P9_21 RX=P9_22
#   UART4 -> TX=P9_13 RX=P9_11
#   UART5 -> TX=P8_37 RX=P8_38
#
# Requer o pacote config-pin (Debian padrao da BeagleBone ja inclui).
# Rode como root (sudo) ou usuario no grupo gpio.

set -euo pipefail

if [[ $# -ne 3 ]]; then
    echo "Uso: $0 <numero_uart> <pino_tx> <pino_rx>" >&2
    exit 1
fi

UART_NUM="$1"
PIN_TX="$2"
PIN_RX="$3"

if ! command -v config-pin >/dev/null 2>&1; then
    echo "Erro: config-pin nao encontrado. Instale com 'apt install config-pin'." >&2
    exit 1
fi

echo "Configurando UART${UART_NUM}: TX=${PIN_TX} RX=${PIN_RX}"
config-pin "${PIN_TX}" uart
config-pin "${PIN_RX}" uart

DEV="/dev/ttyO${UART_NUM}"
if [[ -e "${DEV}" ]]; then
    echo "OK: ${DEV} disponivel."
else
    echo "Aviso: ${DEV} nao apareceu. Pode ser necessario habilitar o overlay" >&2
    echo "correspondente (BB-UART${UART_NUM}) no /boot/uEnv.txt e reiniciar." >&2
    exit 1
fi
