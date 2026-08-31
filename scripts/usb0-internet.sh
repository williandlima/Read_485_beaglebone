#!/bin/sh
# Da internet a BeagleBone atraves do notebook ligado na porta usb0
# (RNDIS/g_ether), quando o notebook esta compartilhando a conexao dele
# via ICS (Internet Connection Sharing) do Windows.
#
# O ICS do Windows sempre usa a faixa 192.168.137.0/24 e se coloca em
# 192.168.137.1, independente da configuracao fixa que a BeagleBone ja
# tem em usb0 (192.168.7.2/30, de /opt/scripts/boot/autoconfigure_usb0.sh
# -- nao mexemos nisso). Este script soma um segundo IP nessa faixa, uma
# rota padrao por ela, e garante um DNS publico -- sem tocar na
# configuracao original.
#
# Instalado como post-up da interface usb0 em /etc/network/interfaces
# (veja scripts/setup_autologin_kiosk.sh ou o README), entao roda
# sozinho sempre que a interface sobe, inclusive apos reboot.
#
# So funciona enquanto o ICS estiver ativo no notebook do lado de la do
# cabo USB. Idempotente: pode rodar de novo a qualquer momento sem
# duplicar nada.

ip addr add 192.168.137.2/24 dev usb0 2>/dev/null
ip route add default via 192.168.137.1 dev usb0 2>/dev/null
grep -q "8.8.8.8" /etc/resolv.conf || echo "nameserver 8.8.8.8" >> /etc/resolv.conf
exit 0
