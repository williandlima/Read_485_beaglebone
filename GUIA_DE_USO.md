# Guia de uso — passo a passo

Este guia é para **usar** o projeto no dia a dia, depois que tudo já
está configurado (BeagleBone com o repositório, driver do conversor,
login automático, etc.). Para configurar do zero, ou para detalhes
técnicos de cada ferramenta, veja o [README.md](README.md).

## 1. Ligar tudo

1. Conecte o conversor USB-RS485 na porta USB-A da BeagleBone (direto,
   ou no hub USB se você também usa mouse/teclado local).
2. Ligue os fios A/B do conversor no barramento RS-485 do equipamento
   que você quer ler.
3. Ligue a BeagleBone na energia (fonte de 5V no conector barrel).
4. Espere ~30 segundos. A tela HDMI deve ir direto para a área de
   trabalho, sem pedir senha (login automático já configurado).

## 2. Abrir o monitor

Na área de trabalho da BeagleBone, dê **duplo clique** no ícone
**"Ler Barramento RS-485"**.

Abre uma janela de terminal com a interface do monitor:

```
RS-485 Monitor - /dev/ttyUSB0 @ 9600 bps  (Q sai, X Excel, H ajuda)
Excel: OFF eventos.xlsx
--------------------------------------------------------------------
DISPOSITIVOS CONHECIDOS
SLAVE  FUNCAO                       PAYLOAD                    QTD  HA
...
--------------------------------------------------------------------
EVENTOS RECENTES
...
```

Se não abrir nada visível, veja a seção **Problemas comuns** abaixo.

**Esqueceu algum atalho?** Aperte **`H`** (ou `?`) a qualquer momento —
abre uma tela de ajuda dentro do próprio programa, com as teclas e o
significado de NOVO/MUDOU. Aperte `H` de novo (ou `Q`) para voltar ao
monitor.

## 3. Ler a tela

- **DISPOSITIVOS CONHECIDOS**: cada linha é uma combinação
  (endereço do escravo + função Modbus) que já apareceu no barramento,
  com o último valor visto, quantas vezes apareceu e há quanto tempo.
- **`*** NOVO ***`**: combinação nunca vista antes.
- **`>>> MUDOU <<<`**: apareceu um valor diferente do que já era
  conhecido — por exemplo, uma chave ou sensor mudou de estado.
- **EVENTOS RECENTES**: histórico dos últimos quadros vistos, mais
  detalhado (payload em hex, se o CRC bateu ou não).

Deixe a tela aberta e observe o equipamento sendo operado — os
destaques aparecem em tempo real conforme o comando muda no barramento.

## 4. Gravar em Excel

Aperte **`X`** a qualquer momento para começar a gravar os eventos numa
planilha (`eventos.xlsx`, salvo na pasta do projeto na BeagleBone). O
cabeçalho muda para `Excel: ON eventos.xlsx`.

Aperte **`X`** de novo para parar de gravar (o arquivo continua
existindo com o que já foi gravado até ali).

Pode ligar e desligar quantas vezes quiser durante a mesma sessão.

## 5. Sair do monitor

Aperte **`Q`**.

## 6. Trazer o Excel para o seu notebook

O arquivo `eventos.xlsx` fica salvo **dentro da BeagleBone** — para
abrir no Excel de verdade, precisa copiar para o Windows.

**Jeito mais fácil**: dê duplo clique em
`scripts/baixar_eventos.bat` (no seu notebook, dentro da cópia local do
repositório). Ele baixa o `eventos.xlsx` da BeagleBone para a mesma
pasta onde está o `.bat`, pedindo a senha do usuário `debian` quando
necessário.

**Ou manualmente**, no PowerShell:
```powershell
scp debian@beaglebone.local:~/Read_485_beaglebone/eventos.xlsx C:\Users\willi\Desktop\
```

Depois é só abrir o arquivo baixado normalmente (duplo clique) no
Excel, LibreOffice ou Google Sheets.

## Problemas comuns

| Sintoma | O que fazer |
| --- | --- |
| Ícone não abre nada visível | Espere ~5s; se nada aparecer, veja `ler_barramento.log` na pasta do projeto (abre como texto normal) — grava o erro e o que aconteceu |
| Tela mostra tudo vazio, sem eventos | Normal se ninguém está perguntando nada ao equipamento no momento; confira se o barramento tem tráfego de verdade |
| `git pull` reclama de DNS/host desconhecido | A internet compartilhada (ICS) não pegou nesse boot — rode `sudo /usr/local/sbin/usb0-internet.sh` e tente de novo |
| `baixar_eventos.bat` falha | Confira se a BeagleBone está ligada e conectada ao notebook via USB, e se você já apertou `X` pelo menos uma vez (o arquivo só existe depois disso) |
| Tela HDMI pede senha de login | Login automático não está configurado — rode `sudo ./scripts/setup_standalone_kiosk.sh` pela SSH |

Para diagnósticos mais profundos (driver do conversor, baudrate
desconhecido, problemas de porta serial), veja as seções técnicas do
[README.md](README.md).
