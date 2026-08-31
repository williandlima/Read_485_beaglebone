# Read_485_beaglebone

Leitura de RS-485 / Modbus RTU na BeagleBone, para engenharia reversa e
integracao com dispositivos no barramento.

> Já tem tudo configurado e só quer usar no dia a dia (ligar, ler a
> tela, gravar em Excel)? Veja o **[Guia de Uso](GUIA_DE_USO.md)** —
> este README aqui é a referência técnica de cada ferramenta.

O projeto tem dois modos de uso:

- **Leitura ativa (mestre Modbus)** — `src/modbus_reader.py`: le
  holding/input registers, coils ou discrete inputs de um escravo Modbus
  RTU conhecido, via `pymodbus`.
- **Sniffer passivo** — `src/rs485_sniffer.py`: apenas escuta o
  barramento, separa os bytes em quadros (pelo criterio de silencio de
  ~3.5 tempos de caractere do Modbus RTU) e tenta decodificar cada
  quadro (endereco, funcao, payload, CRC16), mesmo sem saber o mapa de
  registradores do dispositivo. Ideal para engenharia reversa.

## Hardware

1. **Transceptor RS-485**: um modulo MAX485/SP3485 (ou adaptador
   USB-RS485) ligado ao barramento A/B (D+/D-).
2. **Ligacao com a BeagleBone**:
   - Via adaptador **USB-RS485**: mais simples, aparece como
     `/dev/ttyUSB0`. Normalmente ja faz controle automatico de direcao
     (auto RTS) — recomendado para uso com `modbus_reader.py`.
   - Via **UART direta + MAX485**: TX/RX da BeagleBone ligados ao
     DI/RO do MAX485, e um pino GPIO extra ligado a DE/RE (unidos) para
     controlar a direcao manualmente. Esse modo manual **nao e
     compativel com `modbus_reader.py`** (pymodbus nao expoe hook de
     timing para o GPIO) — use-o apenas em codigo Modbus RTU de baixo
     nivel escrito a mao com `src/frame_parser.py`, ou prefira um
     transceptor com auto RTS.
3. Terminacao de 120 ohm nas duas pontas do barramento, se ainda nao
   houver.

Se for usar UART nativa da BeagleBone Black, veja `scripts/setup_uart.sh`
para habilitar os pinos via `config-pin`.

## Instalacao

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Se for usar controle manual de DE/RE via GPIO (`src/gpio_direction.py`)
em algum script proprio, instale tambem:

```bash
pip install Adafruit_BBIO
```

## Configuracao

Copie o exemplo e ajuste porta serial, baudrate e parametros Modbus:

```bash
cp config/config.example.yaml config/config.yaml
```

## Uso

### Sniffer (engenharia reversa, so escuta)

```bash
python -m src.rs485_sniffer --config config/config.yaml
```

Cada quadro decodificado e impresso com endereco do escravo, codigo de
funcao, payload em hex e validade do CRC — util para identificar o
protocolo mesmo sem documentacao do dispositivo.

### Leitura ativa (mestre Modbus, escravo conhecido)

```bash
python -m src.modbus_reader --config config/config.yaml --continuous
```

### Exemplo standalone (sem arquivo de config)

```bash
python examples/read_holding_registers.py /dev/ttyUSB0 --slave 1 --address 0 --count 10
```

## Estrutura

```
src/
  frame_parser.py     # CRC16 Modbus + decodificacao/montagem de quadros
  modbus_reader.py     # mestre Modbus RTU ativo (pymodbus)
  rs485_sniffer.py      # sniffer passivo para engenharia reversa
  gpio_direction.py     # controle manual de DE/RE via GPIO (Adafruit_BBIO)
config/
  config.example.yaml   # modelo de configuracao (porta, baudrate, etc.)
scripts/
  setup_uart.sh          # habilita UART da BeagleBone via config-pin
examples/
  read_holding_registers.py  # exemplo minimo sem arquivo de config
```

## Descobrir baudrate/paridade (legacy_py34/scan_baudrate.py)

Se voce nao sabe o baudrate/paridade do barramento, esta ferramenta
testa uma lista de combinacoes comuns (9600/19200/38400/57600/115200 x
N/E/O) escutando por alguns segundos em cada uma e contando quantos
quadros com CRC valido aparecem. So escuta, nunca escreve no
barramento. Precisa ter trafego real rolando durante o teste (ex.:
alguem operando o equipamento, ou o CLP fazendo polling).

```bash
python3 legacy_py34/scan_baudrate.py /dev/ttyUSB0
```

A combinacao certa deve aparecer com varios quadros validos; as
erradas normalmente mostram zero. Use `--duration` para escutar mais
tempo em cada combinacao se o trafego for esparso (default 2s).

### O conversor USB-RS485 nao vira /dev/ttyUSB0

Nao existe "driver para instalar" no Linux para esses conversores: os
drivers (`ftdi_sio`, `cp210x`, `pl2303`, `ch341`) ja vem compilados no
kernel. O que acontece com conversores OEM/rebrandeados e que o VID:PID
deles nao esta na tabela de dispositivos conhecidos de nenhum driver -
o kernel enxerga o dispositivo USB (`lsusb` mostra), mas nao liga
nenhum driver serial a ele, e `/dev/ttyUSB0` nunca aparece.

A correcao e registrar o VID:PID no driver certo. `scripts/setup_rs485_usb.sh`
faz isso e instala uma regra de udev para que valha tambem depois de
reiniciar ou reconectar:

```bash
lsusb                                  # ache a linha do conversor: "ID 0856:ac15"
sudo ./scripts/setup_rs485_usb.sh      # default 0856:ac15 (Black Box SP390A-R2)
sudo ./scripts/setup_rs485_usb.sh 0403 6001         # outro VID:PID
sudo ./scripts/setup_rs485_usb.sh 0856 ac15 cp210x  # forcando outro driver
```

Se o `/dev/ttyUSB0` aparecer mas nao abrir com `Input/output error`, o
driver registrado nao e o certo para o chip - repita com `cp210x`,
`pl2303` ou `ch341`.

### Se a porta nao abre

`scan_baudrate.py` e `bus_monitor.py` mostram o erro real do sistema
(errno) e a causa provavel, em vez de so "erro ao abrir a porta". O
errno diz exatamente o que corrigir:

| Erro | Significado | Correcao |
| --- | --- | --- |
| `Permission denied` | usuario sem acesso ao dispositivo | `sudo`, ou `sudo usermod -aG dialout $USER` e relogar |
| `Device or resource busy` | outro processo esta com a porta | `sudo fuser -v /dev/ttyUSB0` e finalizar o processo |
| `No such file or directory` | o dispositivo sumiu | conversor desconectado ou driver descarregado; ver `dmesg \| tail` |
| `Input/output error` | o `/dev/ttyUSB0` existe mas o driver nao fala com o chip | driver errado (ex.: `ftdi_sio` forcado num chip que nao e FTDI); tentar `cp210x`, `pl2303` ou `ch341` |
| `Inappropriate ioctl for device` | o caminho nao e uma porta serial de verdade | conferir o caminho; `ls -l` deve mostrar `c` no inicio |

## Lançador (scripts/ler_barramento.sh)

Reúne num comando só o que hoje precisa de vários passos manuais: achar
a porta serial, ligar o driver do conversor se `/dev/ttyUSB*` ainda não
existir, e apontar o `PYTHONPATH` certo para rodar `bus_monitor.py`.

```bash
./scripts/ler_barramento.sh                       # autodetecta porta, 9600 N
./scripts/ler_barramento.sh --baudrate 19200
./scripts/ler_barramento.sh --parity E --log eventos.log
./scripts/ler_barramento.sh /dev/ttyUSB1 --baudrate 38400
```

Qualquer argumento além da porta é repassado direto para o
`bus_monitor.py` (mesmas opções: `--baudrate`, `--parity`, `--log`).

## Operação autônoma na tela HDMI (scripts/setup_standalone_kiosk.sh)

Para rodar a BeagleBone sozinha — tela HDMI + mouse, sem notebook nem
teclado — faltam duas configurações que são do **sistema**, não do
projeto, e por isso não sobreviveriam a uma reinstalação se ficassem só
na memória de quem configurou:

1. **Login automático (LightDM)**: sem isso, todo reboot para na tela
   de senha, e sem teclado local não dá para digitar.
2. **Internet automática pela `usb0`**: se o notebook do outro lado do
   cabo estiver compartilhando internet via ICS (Compartilhamento de
   Conexão do Windows), a BeagleBone consegue `git pull` sozinha depois
   de um reboot — sem isso, o IP/rota/DNS do ICS (sempre
   `192.168.137.0/24`) se perdem a cada reinicialização e precisam ser
   refeitos na mão.

```bash
sudo ./scripts/setup_standalone_kiosk.sh
```

Idempotente — pode rodar de novo a qualquer momento sem duplicar nada.
Depois, para ver o app: duplo clique no ícone **"Ler Barramento
RS-485"** na área de trabalho (copie `scripts/Ler_Barramento_RS485.desktop`
para `~/Desktop/` se ele ainda não estiver lá) — abre um `xterm` e roda
o monitor, sem precisar de terminal nem digitar nada.

Se o clique duplo não fizer nada visível, veja `ler_barramento.log` na
raiz do projeto (criado pelo `ler_barramento.sh`) — ele grava tudo que
o script imprime, e qualquer saída com erro fica na tela por 2 minutos
antes de fechar sozinha, em vez de sumir na hora.

## Monitor visual do barramento (legacy_py34/bus_monitor.py)

Interface em texto (curses, roda direto no terminal via SSH) que mostra
quais dispositivos/comandos estao presentes no barramento e destaca em
tempo real:

- **NOVO** — combinacao (escravo, funcao, direcao) nunca vista antes
- **MUDOU** — combinacao ja conhecida com um payload diferente do
  anterior (ex.: uma chave/sensor mudou de estado e um novo comando
  apareceu no barramento)

### Pedido do mestre vs. resposta do escravo (coluna DIR)

O sniffer é passivo — não sabe de antemão quem é o mestre e quem é o
escravo, e o Modbus RTU não marca isso no próprio quadro (pedido e
resposta usam o mesmo endereço de escravo e a mesma função). A coluna
**DIR** (`REQ`/`RESP`) resolve isso por **alternância**: o primeiro
quadro de cada combinação (escravo, função) é tratado como pedido do
mestre, o próximo como resposta do escravo, e segue alternando. Isso
faz pedido e resposta aparecerem como **duas linhas separadas** na
tabela (em vez de uma sobrescrever a outra) e evita que `MUDOU` dispare
a cada ciclo só porque pedido e resposta têm payloads diferentes por
natureza — agora só dispara quando o valor de verdade muda.

Limitação honesta: se algum quadro se perder por ruído na linha, a
alternância pode ficar invertida até se autocorrigir (o que costuma
acontecer sozinho no próximo ciclo pergunta→resposta). Também assume
um único mestre no barramento — o cenário normal do Modbus RTU.

Escrito em sintaxe compativel com Python 3.4+ (sem f-strings, sem
dataclasses) porque BeagleBones com imagens antigas (Debian Jessie,
Python 3.4) nao rodam o codigo em `src/`. So depende de `pyserial` e do
modulo `curses` (ja vem no Python padrao).

```bash
python3 legacy_py34/bus_monitor.py /dev/ttyUSB0 --baudrate 9600
```
`Q` para sair, `X` liga/desliga a gravação em Excel (veja abaixo), `H`
ou `?` mostra uma tela de ajuda com as teclas e o significado de
NOVO/MUDOU dentro do próprio programa.

Para guardar so o que importa — quando cada escravo/funcao apareceu
pela primeira vez (o "comando default" daquela combinacao) e toda vez
que um comando diferente aparecer depois — use `--log`:

```bash
python3 legacy_py34/bus_monitor.py /dev/ttyUSB0 --baudrate 9600 --log eventos.log
```

Texto simples, uma linha por evento (sem CRC, sem hex bruto, sem
repeticoes do mesmo valor). O comando default aparece em verde e o
comando novo em amarelo (codigos ANSI, aparecem coloridos ao ver o
arquivo com `cat` no terminal; em editores sem suporte a ANSI, como o
Bloco de Notas do Windows, aparecem como codigos de escape ao redor do
valor, mas o texto continua legivel):

```
01:35:04  DEFAULT   Slave 2  RESP  Read Holding Registers    comando=02 00 00
01:35:06  MUDOU     Slave 2  RESP  Read Holding Registers    default=02 00 00  novo=02 00 01
01:35:09  VOLTOU    Slave 2  RESP  Read Holding Registers    comando=02 00 00
```

(`REQ`/`RESP` é a coluna de direção — veja acima "Pedido do mestre vs.
resposta do escravo".)

Sao tres tipos de linha:

- **DEFAULT** — primeira vez que aquele escravo/funcao aparece com CRC
  valido; define o comando de referencia daquela combinacao
- **MUDOU** — apareceu um comando diferente do default (mostra os dois
  lado a lado)
- **VOLTOU** — o comando voltou a ser exatamente o default

Se o arquivo ja existir, as linhas novas sao anexadas ao final.

### Exportar para Excel (--xlsx)

Os mesmos eventos do `--log` (mesmo criterio: DEFAULT/MUDOU/VOLTOU com
CRC valido) tambem podem ser gravados numa planilha `.xlsx` de verdade,
pronta para abrir no Excel/LibreOffice/Google Sheets:

```bash
python3 legacy_py34/bus_monitor.py /dev/ttyUSB0 --baudrate 9600 --xlsx eventos.xlsx
```

Colunas: Hora, Tipo, Slave, Direção, Funcao, Comando Default, Comando Atual — uma
linha por evento. Pode usar `--log` e `--xlsx` ao mesmo tempo.

Também dá para ligar/desligar a gravação em Excel **de dentro do
monitor**, a qualquer momento, apertando **`X`** — sem precisar
reiniciar com `--xlsx` na linha de comando. Se nenhum `--xlsx` foi
passado, apertar `X` pela primeira vez cria `eventos.xlsx` no diretório
atual; se já havia dispositivos conhecidos antes de ligar, eles entram
no arquivo com um registro DEFAULT no momento em que a tecla foi
apertada, para o arquivo não começar incompleto. O cabeçalho da tela
mostra `Excel: ON eventos.xlsx` ou `Excel: OFF eventos.xlsx` conforme o
estado atual.

O arquivo fica salvo dentro da BeagleBone — para abrir no Excel de
verdade, copie para o Windows. `scripts/baixar_eventos.bat` (rodado no
notebook) faz isso com um duplo clique, sem precisar lembrar do
comando `scp`; veja o [Guia de Uso](GUIA_DE_USO.md#6-trazer-o-excel-para-o-seu-notebook).

O gerador (`legacy_py34/xlsx_writer.py`) nao depende de nenhuma
biblioteca externa (nem `openpyxl`) — monta o `.xlsx` na mao com so a
biblioteca padrao do Python (`.xlsx` e apenas um `.zip` com XML dentro),
pelo mesmo motivo do pyserial estar vendorizado: no precisa de
`pip`/internet na BeagleBone. Diferente do `--log`, que so anexa linhas
novas, o `--xlsx` reescreve o arquivo inteiro a cada evento (não da para
"anexar" a um `.zip` existente de forma simples) — desprezivel para o
volume de eventos de um barramento RS-485.

### Testar sem hardware (legacy_py34/simulate_bus.py)

Gera trafego Modbus RTU valido (CRC correto) em uma porta serial, com um
escravo estavel e outro que simula uma "chave" mudando de estado
periodicamente — util para validar o destaque NOVO/MUDOU antes de ter o
conversor RS-485 e o barramento real em maos.

```bash
# Terminal 1: cria um par de portas seriais virtuais
socat -d -d pty,raw,echo=0,link=/tmp/ttyBUS_A pty,raw,echo=0,link=/tmp/ttyBUS_B

# Terminal 2: gera trafego falso
python3 legacy_py34/simulate_bus.py /tmp/ttyBUS_A --baudrate 9600

# Terminal 3: monitora
python3 legacy_py34/bus_monitor.py /tmp/ttyBUS_B --baudrate 9600
```

Se `socat` nao estiver instalado (ex.: BeagleBone sem internet para
`apt install`), use `legacy_py34/ptybridge.py` no lugar do Terminal 1 —
faz a mesma coisa (cria e interliga dois pseudo-terminais) usando so a
biblioteca padrao do Python:

```bash
# Terminal 1
python3 legacy_py34/ptybridge.py
# imprime algo como:
#   lado A: /dev/pts/3
#   lado B: /dev/pts/4

# Terminal 2 (use o caminho impresso como "lado A")
python3 legacy_py34/simulate_bus.py /dev/pts/3 --baudrate 9600

# Terminal 3 (use o caminho impresso como "lado B")
python3 legacy_py34/bus_monitor.py /dev/pts/4 --baudrate 9600
```

### Simular um escravo Modbus RTU real (legacy_py34/modbus_slave_sim.py)

Diferente do `simulate_bus.py` (que so blasta frames sem serem
pedidos), este simula um dispositivo que **responde a consultas** -
util para validar a cadeia inteira (conversor, driver, pyserial,
consulta ativa, `bus_monitor.py`) sobre um barramento RS-485 de
verdade, sem depender de um equipamento industrial disponivel. Basta
dois conversores na mesma linha A/B: um roda o simulador, o outro
consulta ou so escuta.

So suporta a funcao 0x03 (Read Holding Registers), sobre um banco de
registradores em memoria; o registrador 1 alterna de valor
periodicamente (`--change-every`, default 5s), para testar o destaque
MUDOU.

```bash
python3 legacy_py34/modbus_slave_sim.py /dev/ttyUSB0 --slave 1 --baudrate 9600
python modbus_slave_sim.py COM8 --slave 1 --baudrate 9600   # Windows
```

### Diagnostico de porta sem pyserial (legacy_py34/diagnose_port.py)

Autocontido (so biblioteca padrao) para colar direto num terminal SSH
sem precisar copiar o repositorio inteiro. Separa uma falha no
`open()` do kernel (driver errado, porta ocupada, dispositivo sumido)
de uma falha na configuracao da porta pelo pyserial (termios, baudrate,
paridade) - sao causas diferentes, com correcoes diferentes.

```bash
python3 legacy_py34/diagnose_port.py /dev/ttyUSB0
```

## Driver FTDI no Windows (scripts/fix_ftdi_windows.py)

Conversores com VID:PID de OEM (o padrao aqui, `0856:AC15`, e do Black
Box SP390A-R2) nao constam nos `.inf` da FTDI, entao o Windows nao
vincula o driver sozinho. Forcar a vinculacao pelo Gerenciador de
Dispositivos erra facilmente a camada: o driver de porta (`FTSER2K`)
acaba direto sobre o no USB cru, sem o driver de barramento
(`FTDIBUS`) embaixo. Nesse estado a porta COM abre, aceita `write()` e
reporta "funcionando corretamente" - mas nao emite nenhuma
transferencia USB, entao nenhum byte chega ao chip e o LED de TX nunca
acende. Parece defeito eletrico; e driver mal instalado.

O script diagnostica as duas camadas e corrige selecionando o no de
driver certo diretamente (o mesmo caminho que "Deixe-me escolher entre
uma lista de drivers" usa por baixo), sem depender de casamento de
hardware ID - por isso funciona com VID:PID de OEM. Os binarios
continuam sendo os assinados do DriverStore.

```powershell
python fix_ftdi_windows.py                 # diagnostica, corrige e verifica
python fix_ftdi_windows.py --dry-run       # so diagnostica
python fix_ftdi_windows.py --vid 0403 --pid 6001
python fix_ftdi_windows.py --test COM8     # so o teste de loopback
```

Pede elevação (UAC) sozinho quando precisa. A janela elevada fica
aberta no final esperando Enter, e a saída completa também é salva em
`%TEMP%\fix_ftdi_windows.log` - a janela do UAC fecha sozinha ao
terminar, entao sem isso o relatório se perderia.

## Referencia rapida de comandos

### Acessar a BeagleBone

```bash
ssh debian@192.168.7.2
cd ~/Read_485_beaglebone
```

### Na BeagleBone real (Python 3.4, `legacy_py34/`)

O `serial` vendorizado fica na raiz do projeto, entao os scripts em
`legacy_py34/` precisam de `PYTHONPATH=.` para encontra-lo:

```bash
# Descobrir baudrate/paridade do barramento (precisa de trafego real rolando)
PYTHONPATH=. python3 legacy_py34/scan_baudrate.py /dev/ttyUSB0

# Monitor com o conversor USB-RS485 (ajuste porta/baudrate conforme o barramento)
PYTHONPATH=. python3 legacy_py34/bus_monitor.py /dev/ttyUSB0 --baudrate 9600

# Idem, gravando so o default e as mudancas em texto
PYTHONPATH=. python3 legacy_py34/bus_monitor.py /dev/ttyUSB0 --baudrate 9600 --log eventos.log

# Idem, exportando os mesmos eventos para uma planilha .xlsx
PYTHONPATH=. python3 legacy_py34/bus_monitor.py /dev/ttyUSB0 --baudrate 9600 --xlsx eventos.xlsx

# Testar sem hardware: ponte de portas virtuais (alternativa ao socat)
PYTHONPATH=. python3 -u legacy_py34/ptybridge.py > /tmp/bridge.log 2>&1 &
cat /tmp/bridge.log   # mostra os dois caminhos /dev/pts/N a usar abaixo

# Gerar trafego falso num dos lados da ponte
PYTHONPATH=. python3 legacy_py34/simulate_bus.py /dev/pts/N --baudrate 9600 &

# Monitorar o outro lado
PYTHONPATH=. python3 legacy_py34/bus_monitor.py /dev/pts/M --baudrate 9600

# Encerrar processos de fundo
pkill -f ptybridge.py; pkill -f simulate_bus.py
```

### Em um PC/dev machine com Python 3.6+ (`src/`)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp config/config.example.yaml config/config.yaml

python -m src.rs485_sniffer --config config/config.yaml
python -m src.modbus_reader --config config/config.yaml --continuous
python examples/read_holding_registers.py /dev/ttyUSB0 --slave 1 --address 0 --count 10
```

## pyserial vendorizado (pasta serial/)

O `pyserial` 3.4 esta versionado na raiz do projeto, em `serial/`. Ele e
Python puro e a ultima versao que ainda suporta Python 3.4, entao roda
direto na BeagleBone com Debian Jessie sem precisar de `pip` nem de
internet na placa.

E por isso que os scripts em `legacy_py34/` sao chamados com
`PYTHONPATH=.` a partir da raiz do projeto: e assim que o Python acha
essa copia.

```bash
PYTHONPATH=. python3 legacy_py34/scan_baudrate.py /dev/ttyUSB0
```

Licenca original em `serial/LICENSE.txt` (BSD 3-Clause, Chris Liechti).

### Patch aplicado: EIO ignorado ao setar DTR/RTS na abertura

`serial/serialposix.py` tem uma modificacao em relacao ao pyserial
original: no `open()`, a excecao ao tentar setar DTR/RTS agora tambem
ignora `errno.EIO`, alem de `EINVAL`/`ENOTTY` (que o pyserial ja
ignorava por motivo parecido). Conversores RS-485 tipicamente nao tem
essas linhas fiadas a nada (RS-485 usa so o par A/B), entao o chip pode
nao implementar esse comando de controle, e o driver do kernel retorna
Input/output error - o que antes derrubava a abertura da porta com
`OSError: [Errno 5]` mesmo com o driver certo (`ftdi_sio`) e o
dispositivo saudavel.

Se algum dia vendorizar uma versao mais nova do pyserial, reaplique
esse ajuste em `open()` (procure por `errno.EINVAL, errno.ENOTTY`).
