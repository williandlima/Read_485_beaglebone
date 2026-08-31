#!/usr/bin/env bash
# Liga um conversor USB-RS485 ao driver serial do kernel, de forma
# permanente (sobrevive a reboot e a desconectar/reconectar).
#
# Uso:
#   sudo ./setup_rs485_usb.sh                    # usa 0856:ac15 (Black Box SP390A-R2)
#   sudo ./setup_rs485_usb.sh 0403 6001          # outro VID:PID
#   sudo ./setup_rs485_usb.sh 0856 ac15 cp210x   # forcando outro driver
#
# CONTEXTO
#
# Nao existe "driver para instalar" no Linux para esses conversores: os
# drivers (ftdi_sio, cp210x, pl2303, ch341) ja vem compilados no kernel.
# O que acontece com conversores OEM/rebrandeados e que o VID:PID deles
# nao esta na tabela de dispositivos conhecidos de nenhum driver, entao
# o kernel enxerga o dispositivo USB mas nao liga nenhum driver serial a
# ele - e /dev/ttyUSB0 nunca aparece.
#
# A correcao e registrar o VID:PID no driver certo via 'new_id'. Isso
# vale so ate o proximo boot, entao este script tambem instala uma regra
# de udev que refaz o registro toda vez que o conversor for conectado.
#
# DESCOBRIR O VID:PID: rode 'lsusb' com o conversor conectado e procure
# a linha do seu dispositivo. Em "ID 0856:ac15", 0856 e o VID e ac15 e o
# PID.

set -euo pipefail

VID="${1:-0856}"
PID="${2:-ac15}"
DRIVER="${3:-ftdi_sio}"

RULE_FILE="/etc/udev/rules.d/99-rs485-${VID}-${PID}.rules"

if [[ "${EUID}" -ne 0 ]]; then
    echo "Erro: rode como root (sudo $0 ...)." >&2
    exit 1
fi

echo "Conversor ${VID}:${PID} -> driver ${DRIVER}"

if ! lsusb -d "${VID}:${PID}" >/dev/null 2>&1; then
    echo "Aviso: nenhum dispositivo ${VID}:${PID} conectado agora." >&2
    echo "A regra sera instalada mesmo assim e valera quando ele for plugado." >&2
fi

# 1) Carrega o driver e registra o VID:PID agora, para valer nesta sessao.
modprobe "${DRIVER}"

NEW_ID="/sys/bus/usb-serial/drivers/${DRIVER}/new_id"
if [[ ! -w "${NEW_ID}" ]]; then
    echo "Erro: ${NEW_ID} nao existe. O driver '${DRIVER}' nao expoe new_id" >&2
    echo "(nome errado, ou o modulo nao carregou). Drivers comuns:" >&2
    echo "  ftdi_sio  cp210x  pl2303  ch341" >&2
    exit 1
fi

# Ja registrado antes? Escrever de novo devolve EINVAL - nao e erro.
echo "${VID} ${PID}" > "${NEW_ID}" 2>/dev/null || true

# 2) Torna permanente: a regra refaz o registro a cada conexao.
cat > "${RULE_FILE}" <<EOF
# Conversor USB-RS485 ${VID}:${PID}: o VID:PID nao esta na tabela do
# ${DRIVER}, entao registramos por new_id sempre que ele for conectado.
ACTION=="add", SUBSYSTEM=="usb", ATTR{idVendor}=="${VID}", ATTR{idProduct}=="${PID}", \\
  RUN+="/bin/sh -c 'modprobe ${DRIVER}; echo ${VID} ${PID} > /sys/bus/usb-serial/drivers/${DRIVER}/new_id'"
EOF

udevadm control --reload-rules
echo "Regra instalada em ${RULE_FILE}"

# 3) Confere o resultado.
sleep 1
shopt -s nullglob
PORTS=(/dev/ttyUSB*)
if [[ ${#PORTS[@]} -gt 0 ]]; then
    echo
    echo "Portas seriais disponiveis:"
    ls -l "${PORTS[@]}"
    echo
    echo "Se o seu usuario nao estiver no grupo dono da porta (normalmente"
    echo "dialout), adicione-o e faca logout/login:"
    echo "  sudo usermod -aG dialout \$SUDO_USER"
else
    echo
    echo "Nenhum /dev/ttyUSB* apareceu. Veja o motivo com:" >&2
    echo "  dmesg | tail -20" >&2
    echo
    echo "Se o dmesg mostrar o dispositivo sendo detectado mas nenhum" >&2
    echo "'converter now attached to ttyUSB0', o driver '${DRIVER}' provavelmente" >&2
    echo "nao e o certo para o chip. Tente os outros:" >&2
    echo "  sudo $0 ${VID} ${PID} cp210x" >&2
    echo "  sudo $0 ${VID} ${PID} pl2303" >&2
    echo "  sudo $0 ${VID} ${PID} ch341" >&2
    exit 1
fi
