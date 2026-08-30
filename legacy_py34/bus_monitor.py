# -*- coding: utf-8 -*-
"""Monitor de barramento RS-485/Modbus RTU com interface em texto (curses).

Standalone e escrito em sintaxe compativel com Python 3.4+ (sem f-strings,
sem dataclasses, sem type hints) para rodar direto em BeagleBones com
imagens antigas, sem precisar instalar nada alem do pyserial.

Mostra:
  - uma tabela de "quem esta no barramento": um registro por combinacao
    (endereco do escravo, codigo de funcao), com o ultimo payload visto,
    quantas vezes apareceu e ha quanto tempo;
  - destaque quando aparece uma combinacao NUNCA vista antes (NOVO), ou
    quando uma combinacao ja conhecida aparece com um payload DIFERENTE
    do anterior (MUDOU) - por exemplo, quando uma chave/sensor muda de
    estado e um novo comando aparece no barramento;
  - um log de eventos recentes, mais completo, abaixo da tabela.

Uso:
    python3 bus_monitor.py /dev/ttyUSB0 --baudrate 9600
    python3 bus_monitor.py /dev/ttyUSB0 --baudrate 9600 --log eventos.log
    python3 bus_monitor.py /dev/ttyUSB0 --baudrate 9600 --xlsx eventos.xlsx
    (Q para sair, X liga/desliga a gravacao em Excel, H mostra ajuda)

Com --log, so o que importa e gravado em texto simples, uma linha por
evento, de tres tipos:

  DEFAULT  primeira vez que aquele escravo/funcao aparece com CRC
           valido; define o "comando default" daquela combinacao
  MUDOU    apareceu um comando diferente do default (mostra os dois
           lado a lado)
  VOLTOU   o comando voltou a ser exatamente o default

Repeticoes do mesmo valor nao sao gravadas. Se o arquivo ja existir, as
linhas novas sao anexadas ao final.

Com --xlsx, os mesmos eventos (mesmo criterio de --log) sao gravados
numa planilha .xlsx de verdade, com uma coluna por campo -- pronta para
abrir no Excel/LibreOffice/Google Sheets, filtrar e ordenar. Pode usar
--log e --xlsx juntos. Diferente do --log, o --xlsx sempre reescreve o
arquivo do zero a cada evento -- nao ha como "anexar" a um .xlsx
existente de forma simples.

A gravacao em Excel tambem pode ser ligada/desligada a qualquer momento
com a tecla X, sem precisar reiniciar o programa -- util para so
comecar a gravar quando algo interessante começar a acontecer no
barramento. Se --xlsx nao foi passado na linha de comando, apertar X
cria eventos.xlsx no diretorio atual; se ja tinha uma combinacao
escravo/funcao conhecida antes de ligar, ela entra no arquivo com um
registro DEFAULT no momento em que X foi apertado, para o arquivo nao
comecar incompleto.
"""
import argparse
import curses
import sys
import time
from collections import deque

import serial

from portdiag import OPEN_ERRORS, read_timeout_for, report_open_error
from xlsx_writer import write_xlsx

FUNCTION_NAMES = {
    0x01: "Read Coils",
    0x02: "Read Discrete Inputs",
    0x03: "Read Holding Registers",
    0x04: "Read Input Registers",
    0x05: "Write Single Coil",
    0x06: "Write Single Register",
    0x0F: "Write Multiple Coils",
    0x10: "Write Multiple Registers",
    0x16: "Mask Write Register",
    0x17: "Read/Write Multiple Registers",
}

NEW_HIGHLIGHT_SECONDS = 6.0
CHANGED_HIGHLIGHT_SECONDS = 6.0
MAX_EVENTS = 300


def crc16_modbus(data):
    crc = 0xFFFF
    for byte in bytearray(data):
        crc ^= byte
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc & 0xFFFF


def hexlify_spaced(data):
    return ' '.join('%02x' % b for b in bytearray(data))


def function_name(function_code):
    return FUNCTION_NAMES.get(function_code & 0x7F, "FC 0x%02X" % (function_code & 0x7F))


def parse_frame(data):
    if len(data) < 4:
        return None
    slave_id = data[0]
    function_code = data[1]
    payload = bytes(data[2:-2])
    crc_received = data[-2] | (data[-1] << 8)
    crc_calculated = crc16_modbus(data[:-2])
    return {
        'slave_id': slave_id,
        'function_code': function_code,
        'payload': payload,
        'crc_ok': crc_received == crc_calculated,
        'raw': bytes(data),
    }


def char_time_seconds(baudrate, bytesize=8, parity='N', stopbits=1):
    parity_bits = 0 if parity.upper() == 'N' else 1
    bits_per_char = 1 + bytesize + parity_bits + stopbits
    return float(bits_per_char) / baudrate


def fmt_ago(seconds):
    if seconds < 1:
        return "agora"
    if seconds < 60:
        return "%ds" % int(seconds)
    if seconds < 3600:
        return "%dmin" % int(seconds / 60)
    return "%dh" % int(seconds / 3600)


def safe_addstr(win, y, x, text, attr=0):
    h, w = win.getmaxyx()
    if y < 0 or y >= h or x >= w:
        return
    max_len = w - x - 1
    if max_len <= 0:
        return
    try:
        win.addstr(y, x, text[:max_len], attr)
    except curses.error:
        pass


def update_registry(registry, registry_order, frame, now):
    """Atualiza o registro de dispositivos conhecidos com um novo quadro.

    Retorna a string de status ('new', 'changed' ou None) para este quadro.
    """
    key = (frame['slave_id'], frame['function_code'])
    prev = registry.get(key)
    status = None
    if prev is None:
        status = 'new'
        registry_order.append(key)
    elif prev['payload'] != frame['payload']:
        status = 'changed'

    entry = {
        'payload': frame['payload'],
        'crc_ok': frame['crc_ok'],
        'count': (prev['count'] + 1) if prev else 1,
        'last_seen': now,
        'status': status if status else (prev['status'] if prev else None),
        'status_until': (now + (NEW_HIGHLIGHT_SECONDS if status == 'new' else CHANGED_HIGHLIGHT_SECONDS))
                        if status else (prev['status_until'] if prev else 0),
    }
    registry[key] = entry
    return status


ANSI_GREEN = '\033[92m'
ANSI_YELLOW = '\033[93m'
ANSI_RESET = '\033[0m'


def open_log(path):
    return open(path, 'a')


def log_default(log_file, now, frame):
    """Grava a linha que define o comando default de um escravo/funcao
    (a primeira vez que ele aparece no barramento)."""
    when = time.strftime('%H:%M:%S', time.localtime(now))
    line = "%s  DEFAULT   Slave %d  %-24s  comando=%s%s%s\n" % (
        when, frame['slave_id'], function_name(frame['function_code']),
        ANSI_GREEN, hexlify_spaced(frame['payload']), ANSI_RESET)
    log_file.write(line)
    log_file.flush()


def log_return(log_file, now, frame):
    """Grava quando o payload volta a ser exatamente o comando default.

    Sem isso a linha sairia como MUDOU com 'novo' igual ao 'default', o
    que se le como uma contradicao.
    """
    when = time.strftime('%H:%M:%S', time.localtime(now))
    line = "%s  VOLTOU    Slave %d  %-24s  comando=%s%s%s\n" % (
        when, frame['slave_id'], function_name(frame['function_code']),
        ANSI_GREEN, hexlify_spaced(frame['payload']), ANSI_RESET)
    log_file.write(line)
    log_file.flush()


def log_change(log_file, now, frame, default_payload):
    """Grava a linha de uma mudanca: comando default vs comando novo.

    O comando novo aparece em amarelo (codigo ANSI) para se destacar
    quando o arquivo e visto com 'cat' no terminal.
    """
    when = time.strftime('%H:%M:%S', time.localtime(now))
    line = "%s  MUDOU     Slave %d  %-24s  default=%s  novo=%s%s%s\n" % (
        when, frame['slave_id'], function_name(frame['function_code']),
        hexlify_spaced(default_payload),
        ANSI_YELLOW, hexlify_spaced(frame['payload']), ANSI_RESET)
    log_file.write(line)
    log_file.flush()


XLSX_HEADERS = ['Hora', 'Tipo', 'Slave', 'Funcao', 'Comando Default', 'Comando Atual']


class XlsxLog(object):
    """Acumula as linhas de evento em memoria e reescreve o .xlsx inteiro
    a cada evento novo (mesmo criterio do --log: DEFAULT/MUDOU/VOLTOU com
    CRC valido). Reescrever tudo a cada evento e desprezivel para o
    volume de eventos de um barramento RS-485 (nao e um log byte a
    byte), e evita ter que manipular um .zip existente incrementalmente."""

    def __init__(self, path):
        self.path = path
        self.rows = []

    def add(self, now, tipo, frame, default_payload=None):
        when = time.strftime('%H:%M:%S', time.localtime(now))
        atual = hexlify_spaced(frame['payload'])
        default = hexlify_spaced(default_payload) if default_payload is not None else atual
        self.rows.append([
            when, tipo, frame['slave_id'],
            function_name(frame['function_code']), default, atual,
        ])
        write_xlsx(self.path, XLSX_HEADERS, self.rows)


DEFAULT_XLSX_PATH = "eventos.xlsx"


def run(stdscr, ser, silence, port_desc, log=None, xlsx=None):
    curses.curs_set(0)
    has_color = curses.has_colors()
    if has_color:
        curses.start_color()
        try:
            curses.use_default_colors()
            bg = -1
        except curses.error:
            bg = curses.COLOR_BLACK
        curses.init_pair(1, curses.COLOR_GREEN, bg)
        curses.init_pair(2, curses.COLOR_YELLOW, bg)
        curses.init_pair(3, curses.COLOR_RED, bg)
        curses.init_pair(4, curses.COLOR_CYAN, bg)
        attr_new = curses.color_pair(1) | curses.A_BOLD
        attr_changed = curses.color_pair(2) | curses.A_BOLD
        attr_bad_crc = curses.color_pair(3) | curses.A_BOLD
        attr_header = curses.color_pair(4) | curses.A_BOLD
    else:
        attr_new = curses.A_BOLD
        attr_changed = curses.A_BOLD
        attr_bad_crc = curses.A_REVERSE
        attr_header = curses.A_BOLD

    # getch() nao pode bloquear: quem dita o ritmo do laco e a leitura da
    # serial (ser.timeout, ajustado em main() para menos que o silencio
    # entre quadros). Um stdscr.timeout(100) aqui prenderia o laco em ~10
    # iteracoes/s e os quadros do barramento chegariam grudados.
    stdscr.nodelay(True)
    stdscr.timeout(0)

    registry = {}
    registry_order = []
    events = deque(maxlen=MAX_EVENTS)
    defaults = {}

    # Caminho lembrado mesmo com a gravacao desligada, so para mostrar na
    # tela qual arquivo seria usado se a tecla X for apertada de novo.
    xlsx_path = xlsx.path if xlsx is not None else DEFAULT_XLSX_PATH

    buffer = bytearray()
    last_byte_time = None
    mostrar_ajuda = False

    while True:
        ch = stdscr.getch()
        if ch in (ord('q'), ord('Q')):
            break
        if ch in (ord('h'), ord('H'), ord('?')):
            mostrar_ajuda = not mostrar_ajuda
        if ch in (ord('x'), ord('X')):
            if xlsx is None:
                xlsx = XlsxLog(xlsx_path)
                xlsx_path = xlsx.path
                now = time.time()
                # Semeia com os defaults ja conhecidos, para o arquivo nao
                # comecar faltando os dispositivos vistos antes de ligar.
                for key, payload in defaults.items():
                    slave_id, function_code = key
                    frame = {'slave_id': slave_id, 'function_code': function_code,
                             'payload': payload}
                    xlsx.add(now, 'DEFAULT', frame)
            else:
                xlsx = None

        chunk = ser.read(256)
        now = time.time()

        if chunk:
            buffer.extend(chunk)
            last_byte_time = now
        elif buffer and last_byte_time is not None and (now - last_byte_time) >= silence:
            frame = parse_frame(bytes(buffer))
            if frame is not None:
                key = (frame['slave_id'], frame['function_code'])
                status = update_registry(registry, registry_order, frame, now)
                events.appendleft((now, status, frame))
                if (log is not None or xlsx is not None) and frame['crc_ok']:
                    default_payload = defaults.get(key)
                    if default_payload is None:
                        # O primeiro quadro VALIDO desta combinacao define o
                        # default. Nao da para usar status == 'new' aqui: se o
                        # primeiro quadro visto tinha CRC ruim, ele ja marcou a
                        # combinacao como conhecida sem definir default nenhum.
                        defaults[key] = frame['payload']
                        if log is not None:
                            log_default(log, now, frame)
                        if xlsx is not None:
                            xlsx.add(now, 'DEFAULT', frame)
                    elif status == 'changed':
                        if frame['payload'] == default_payload:
                            if log is not None:
                                log_return(log, now, frame)
                            if xlsx is not None:
                                xlsx.add(now, 'VOLTOU', frame)
                        else:
                            if log is not None:
                                log_change(log, now, frame, default_payload)
                            if xlsx is not None:
                                xlsx.add(now, 'MUDOU', frame, default_payload)
            else:
                frame = {
                    'raw': bytes(buffer), 'slave_id': None,
                    'function_code': None, 'payload': b'', 'crc_ok': False,
                }
                events.appendleft((now, None, frame))
            buffer = bytearray()
            last_byte_time = None

        if mostrar_ajuda:
            draw_help(stdscr, attr_header)
        else:
            xlsx_status = "ON  %s" % xlsx_path if xlsx is not None else "OFF %s" % xlsx_path
            draw(stdscr, registry, registry_order, events, now, port_desc, xlsx_status,
                 attr_new, attr_changed, attr_bad_crc, attr_header)


HELP_LINES = [
    "AJUDA - RS-485 Monitor    (aperte H, ? ou Q para voltar)",
    "",
    "TECLAS",
    "  Q       sai do monitor",
    "  X       liga/desliga a gravacao dos eventos em eventos.xlsx",
    "  H ou ?  mostra/esconde esta ajuda",
    "",
    "COMO LER A TELA",
    "  DISPOSITIVOS CONHECIDOS  combinacoes (escravo+funcao) ja vistas,",
    "                           com ultimo valor, quantas vezes e ha quanto",
    "  *** NOVO ***             combinacao nunca vista antes",
    "  >>> MUDOU <<<            valor diferente do que ja era conhecido",
    "  EVENTOS RECENTES         historico detalhado (payload em hex)",
    "",
    "SOBRE O EXCEL (tecla X)",
    "  O .xlsx fica salvo na BeagleBone. Para abrir no Excel de verdade,",
    "  copie para o computador: scripts/baixar_eventos.bat (Windows), ou",
    "  scp. Passo a passo completo: GUIA_DE_USO.md no repositorio.",
    "",
    "(H, ? ou Q para voltar)",
]


def draw_help(stdscr, attr_header):
    stdscr.erase()
    h, w = stdscr.getmaxyx()
    for i, line in enumerate(HELP_LINES):
        if i >= h - 1:
            break
        attr = attr_header if i == 0 else 0
        safe_addstr(stdscr, i, 0, line, attr)


def draw(stdscr, registry, registry_order, events, now, port_desc, xlsx_status,
         attr_new, attr_changed, attr_bad_crc, attr_header):
    stdscr.erase()
    h, w = stdscr.getmaxyx()

    safe_addstr(stdscr, 0, 0, "RS-485 Monitor - %s  (Q sai, X Excel, H ajuda)" % port_desc,
                attr_header)
    safe_addstr(stdscr, 1, 0, "Excel: %s" % xlsx_status,
                (attr_new if xlsx_status.startswith("ON") else 0))
    safe_addstr(stdscr, 2, 0, "-" * (w - 1))
    safe_addstr(stdscr, 3, 0, "DISPOSITIVOS CONHECIDOS", attr_header)
    header = "%-6s %-28s %-24s %5s  %-6s" % ("SLAVE", "FUNCAO", "PAYLOAD", "QTD", "HA")
    safe_addstr(stdscr, 4, 0, header, curses.A_UNDERLINE)

    max_device_rows = max(3, (h - 9) // 2)
    row = 5
    drawn = 0
    for key in registry_order:
        if drawn >= max_device_rows:
            break
        entry = registry.get(key)
        if entry is None:
            continue
        slave_id, function_code = key
        attr = 0
        tag = ""
        if entry['status'] and now < entry['status_until']:
            if entry['status'] == 'new':
                attr = attr_new
                tag = " *** NOVO ***"
            elif entry['status'] == 'changed':
                attr = attr_changed
                tag = " >>> MUDOU <<<"
        if not entry['crc_ok']:
            attr = attr_bad_crc
        line = "%-6d %-28s %-24s %5d  %-6s%s" % (
            slave_id, function_name(function_code), hexlify_spaced(entry['payload']),
            entry['count'], fmt_ago(now - entry['last_seen']), tag)
        safe_addstr(stdscr, row, 0, line, attr)
        row += 1
        drawn += 1

    sep_row = row + 1
    safe_addstr(stdscr, sep_row, 0, "-" * (w - 1))
    safe_addstr(stdscr, sep_row + 1, 0, "EVENTOS RECENTES", attr_header)

    event_row = sep_row + 2
    for item in events:
        ts, status, frame = item
        if event_row >= h - 1:
            break
        when = time.strftime("%H:%M:%S", time.localtime(ts))
        if frame.get('slave_id') is None:
            text = "%s BLOCO CURTO raw=%s" % (when, hexlify_spaced(frame['raw']))
            attr = 0
        else:
            crc_txt = "OK" if frame['crc_ok'] else "CRC INVALIDO"
            attr = 0
            if status == 'new':
                tag = "NOVO  "
                attr = attr_new
            elif status == 'changed':
                tag = "MUDOU "
                attr = attr_changed
            else:
                tag = "....  "
            if not frame['crc_ok']:
                attr = attr_bad_crc
            text = "%s %sSlave=%d FC=0x%02X (%s) Payload=%s CRC=%s" % (
                when, tag, frame['slave_id'], frame['function_code'],
                function_name(frame['function_code']), hexlify_spaced(frame['payload']), crc_txt)
        safe_addstr(stdscr, event_row, 0, text, attr)
        event_row += 1

    stdscr.refresh()


def main():
    parser = argparse.ArgumentParser(description="Monitor visual de barramento RS-485/Modbus RTU")
    parser.add_argument('port', help="Porta serial, ex.: /dev/ttyUSB0")
    parser.add_argument('--baudrate', type=int, default=9600)
    parser.add_argument('--parity', default='N', choices=['N', 'E', 'O'])
    parser.add_argument('--stopbits', type=int, default=1)
    parser.add_argument('--log', default=None,
                         help="Caminho de um arquivo de texto onde e gravado "
                              "o comando default de cada escravo/funcao e "
                              "toda mudanca em relacao a ele (anexa se ja existir)")
    parser.add_argument('--xlsx', default=None,
                         help="Caminho de uma planilha .xlsx onde os mesmos "
                              "eventos do --log sao gravados, uma coluna por "
                              "campo (sobrescreve o arquivo a cada evento)")
    args = parser.parse_args()

    silence = max(char_time_seconds(args.baudrate, 8, args.parity, args.stopbits) * 3.5, 0.005)

    try:
        ser = serial.Serial(args.port, args.baudrate, parity=args.parity,
                             stopbits=args.stopbits,
                             timeout=read_timeout_for(silence))
    except OPEN_ERRORS as exc:
        report_open_error(sys.stderr.write, args.port, exc)
        return 1
    port_desc = "%s @ %s bps" % (args.port, args.baudrate)

    log = open_log(args.log) if args.log else None
    xlsx = XlsxLog(args.xlsx) if args.xlsx else None

    try:
        curses.wrapper(run, ser, silence, port_desc, log, xlsx)
    finally:
        ser.close()
        if log is not None:
            log.close()


if __name__ == '__main__':
    sys.exit(main() or 0)
