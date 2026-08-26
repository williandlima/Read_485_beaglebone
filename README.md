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
