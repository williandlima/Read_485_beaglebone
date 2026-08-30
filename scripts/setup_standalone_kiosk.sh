#!/usr/bin/env bash
# Deixa a BeagleBone pronta para operar sozinha, sem teclado nem
# notebook: tela HDMI com login automatico, e internet automatica pela
# usb0 quando o notebook do outro lado do cabo estiver compartilhando
# conexao via ICS.
#
# Reproduz em uma tacada so as duas configuracoes que foram feitas na
# mao durante o desenvolvimento deste projeto (e que, por serem
# configuracao de sistema fora do repositorio, se perderiam numa
# reinstalacao):
#
#   1. LightDM: login automatico do usuario 'debian' (scripts/../
#      ler_barramento.sh so abre por clique duplo se a tela HDMI ja
#      estiver no desktop -- sem isso, cada reboot exige teclado para
#      digitar a senha na tela de login).
#   2. usb0: instala scripts/usb0-internet.sh como post-up da interface,
#      para a internet compartilhada (ICS) sobreviver a reboot sem
#      precisar repetir os comandos manuais.
#
# Idempotente: pode rodar de novo a qualquer momento sem duplicar nada.
#
# Uso:
#   sudo ./scripts/setup_standalone_kiosk.sh

set -euo pipefail

if [[ "$(id -u)" -ne 0 ]]; then
    echo "Precisa rodar como root: sudo $0"
    exit 1
fi

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "=== 1. Login automatico (LightDM) ==="
LIGHTDM_CONF="/etc/lightdm/lightdm.conf"
if [[ -f "$LIGHTDM_CONF" ]]; then
    if grep -q "^autologin-user=debian" "$LIGHTDM_CONF"; then
        echo "Ja configurado."
    else
        sed -i 's/^#autologin-user=debian/autologin-user=debian/' "$LIGHTDM_CONF"
        sed -i 's/^#autologin-user-timeout=0/autologin-user-timeout=0/' "$LIGHTDM_CONF"
        if grep -q "^autologin-user=debian" "$LIGHTDM_CONF"; then
            echo "Configurado. Reinicie o LightDM para valer (ou reboot):"
            echo "  sudo systemctl restart lightdm"
        else
            echo "AVISO: nao encontrei as linhas 'autologin-user'/'autologin-user-timeout'"
            echo "comentadas em $LIGHTDM_CONF (formato pode ser diferente nesta imagem)."
            echo "Adicione manualmente na secao [SeatDefaults]:"
            echo "  autologin-user=debian"
            echo "  autologin-user-timeout=0"
        fi
    fi
else
    echo "LightDM nao encontrado ($LIGHTDM_CONF nao existe) -- pulando."
    echo "(normal se a imagem nao usa desktop grafico)"
fi

echo
echo "=== 2. Internet automatica pela usb0 (ICS) ==="
install -m 755 "$RAIZ/scripts/usb0-internet.sh" /usr/local/sbin/usb0-internet.sh
echo "Instalado em /usr/local/sbin/usb0-internet.sh"

INTERFACES="/etc/network/interfaces"
if grep -q "post-up /usr/local/sbin/usb0-internet.sh" "$INTERFACES"; then
    echo "Gancho post-up ja estava configurado em $INTERFACES."
else
    if grep -q "gateway 192.168.7.1" "$INTERFACES"; then
        sed -i '/gateway 192.168.7.1/a\    post-up /usr/local/sbin/usb0-internet.sh' "$INTERFACES"
        echo "Gancho post-up adicionado em $INTERFACES."
    else
        echo "AVISO: nao encontrei 'gateway 192.168.7.1' em $INTERFACES"
        echo "(formato pode ser diferente nesta imagem). Adicione manualmente,"
        echo "dentro do bloco 'iface usb0 inet static':"
        echo "    post-up /usr/local/sbin/usb0-internet.sh"
    fi
fi

echo
echo "=== Feito ==="
echo "Rode /usr/local/sbin/usb0-internet.sh manualmente agora se quiser"
echo "internet ja nesta sessao, sem esperar o proximo reboot:"
echo "  sudo /usr/local/sbin/usb0-internet.sh"
