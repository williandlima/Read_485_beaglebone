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

# Alguns caminhos de lancamento (clique duplo via gerenciador de
# arquivos, associacao de MIME type com um terminal) nao propagam TERM
# para o processo filho. Sem TERM, o curses do Python nao acha o
# terminfo e falha com "setupterm: could not find terminal" antes
# mesmo de desenhar a primeira tela.
export TERM="${TERM:-xterm}"

# Quando aberto por clique duplo (Xterm etc.), a janela fecha sozinha
# assim que o script termina -- se der erro antes de chegar no monitor,
# ninguem consegue ler a mensagem a tempo. Grava tudo num log e, em
# qualquer saida com erro, pausa por um tempo generoso antes de fechar.
LOG="$RAIZ/ler_barramento.log"
exec > >(tee -a "$LOG") 2>&1
echo "--- $(date '+%Y-%m-%d %H:%M:%S') ---"

falhar() {
    echo "ERRO: $1"
    echo "(log completo em $LOG)"
    echo "Essa janela fecha sozinha em 2 minutos -- ou feche manualmente."
    sleep 120
    exit 1
}

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
    falhar "Nenhuma porta serial disponivel. Confira: o conversor esta conectado? Aparece em 'lsusb'?"
fi

echo "Usando porta: $PORTA"
# Sem 'exec' aqui de proposito: se bus_monitor.py falhar (crash, porta
# ocupada, etc.), precisamos que o bash continue vivo depois pra chamar
# falhar() e segurar a janela -- com 'exec' o processo seria substituido
# e a janela fecharia junto com o erro, sem tempo de leitura.
#
# ${ARGS[@]+"${ARGS[@]}"} em vez de "${ARGS[@]}": bash < 4.4 (ex.: o desta
# BeagleBone, Debian Jessie) trata um array vazio como variavel nao
# definida sob 'set -u' e aborta com "unbound variable".
set +e
# PYTHONFAULTHANDLER=1: se der segfault (codigo 139) de novo, o Python
# imprime o traceback nativo (pilha de chamadas em C) antes de morrer,
# em vez de so cair sem explicacao nenhuma.
env PYTHONPATH="$RAIZ" PYTHONFAULTHANDLER=1 python3 "$RAIZ/legacy_py34/bus_monitor.py" "$PORTA" ${ARGS[@]+"${ARGS[@]}"}
codigo=$?
set -e

if [[ $codigo -ne 0 ]]; then
    if [[ $codigo -eq 139 ]]; then
        falhar "bus_monitor.py morreu com SEGMENTATION FAULT (codigo 139). Veja o traceback nativo acima/no log."
    else
        falhar "bus_monitor.py terminou com codigo $codigo."
    fi
fi
