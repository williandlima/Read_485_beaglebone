# Read_485_beaglebone

Leitura de RS-485 / Modbus RTU na BeagleBone, para engenharia reversa e
integracao com dispositivos no barramento.

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

## Monitor visual do barramento (legacy_py34/bus_monitor.py)

Interface em texto (curses, roda direto no terminal via SSH) que mostra
quais dispositivos/comandos estao presentes no barramento e destaca em
tempo real:

- **NOVO** — combinacao (escravo, funcao) nunca vista antes
- **MUDOU** — combinacao ja conhecida com um payload diferente do
  anterior (ex.: uma chave/sensor mudou de estado e um novo comando
  apareceu no barramento)

Escrito em sintaxe compativel com Python 3.4+ (sem f-strings, sem
dataclasses) porque BeagleBones com imagens antigas (Debian Jessie,
Python 3.4) nao rodam o codigo em `src/`. So depende de `pyserial` e do
modulo `curses` (ja vem no Python padrao).

```bash
python3 legacy_py34/bus_monitor.py /dev/ttyUSB0 --baudrate 9600
```
`Q` para sair.

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
01:35:04  DEFAULT   Slave 2  Read Holding Registers    comando=02 00 00
01:35:06  MUDOU     Slave 2  Read Holding Registers    default=02 00 00  novo=02 00 01
01:35:09  MUDOU     Slave 2  Read Holding Registers    default=02 00 00  novo=02 00 00
```

Se o arquivo ja existir, as linhas novas sao anexadas ao final.

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
