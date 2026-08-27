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
    python3 bus_monitor.py /dev/ttyUSB0 --baudrate 9600 --log eventos.csv
    (Q para sair)

Com --log, cada evento (quadro completo, valido ou nao) e gravado em um
CSV conforme acontece, com timestamp, status (new/changed/vazio),
escravo, funcao, payload e CRC - para consultar depois de fechar o
monitor. Se o arquivo ja existir, os eventos novos sao anexados ao
final (o cabecalho so e escrito uma vez).
"""
import argparse
import csv
import curses
import os
import time
from collections import deque

import serial

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


LOG_HEADER = ['timestamp', 'status', 'slave_id', 'function_code',
              'function_name', 'payload_hex', 'crc_ok', 'raw_hex']


def open_log(path):
    is_new = not (os.path.isfile(path) and os.path.getsize(path) > 0)
    f = open(path, 'a', newline='')
    writer = csv.writer(f)
    if is_new:
        writer.writerow(LOG_HEADER)
        f.flush()
    return f, writer


def log_event(log_file, log_writer, now, status, frame):
    slave_id = frame.get('slave_id')
    function_code = frame.get('function_code')
    row = [
        time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(now)),
        status if status else '',
        slave_id if slave_id is not None else '',
        ('0x%02X' % function_code) if function_code is not None else '',
        function_name(function_code) if function_code is not None else '',
        hexlify_spaced(frame.get('payload', b'')),
        'OK' if frame.get('crc_ok') else 'BAD',
        hexlify_spaced(frame.get('raw', b'')),
    ]
    log_writer.writerow(row)
    log_file.flush()


def run(stdscr, ser, silence, port_desc, log=None):
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

    stdscr.nodelay(True)
    stdscr.timeout(100)

    registry = {}
    registry_order = []
    events = deque(maxlen=MAX_EVENTS)

    buffer = bytearray()
    last_byte_time = None

    while True:
        ch = stdscr.getch()
        if ch in (ord('q'), ord('Q')):
            break

        chunk = ser.read(256)
        now = time.time()

        if chunk:
            buffer.extend(chunk)
            last_byte_time = now
        elif buffer and last_byte_time is not None and (now - last_byte_time) >= silence:
            frame = parse_frame(bytes(buffer))
            if frame is not None:
                status = update_registry(registry, registry_order, frame, now)
                events.appendleft((now, status, frame))
            else:
                status = None
                frame = {
                    'raw': bytes(buffer), 'slave_id': None,
                    'function_code': None, 'payload': b'', 'crc_ok': False,
                }
                events.appendleft((now, status, frame))
            if log is not None:
                log_event(log[0], log[1], now, status, frame)
            buffer = bytearray()
            last_byte_time = None

        draw(stdscr, registry, registry_order, events, now, port_desc,
             attr_new, attr_changed, attr_bad_crc, attr_header)


def draw(stdscr, registry, registry_order, events, now, port_desc,
         attr_new, attr_changed, attr_bad_crc, attr_header):
    stdscr.erase()
    h, w = stdscr.getmaxyx()

    safe_addstr(stdscr, 0, 0, "RS-485 Monitor - %s  (Q sai)" % port_desc, attr_header)
    safe_addstr(stdscr, 1, 0, "-" * (w - 1))
    safe_addstr(stdscr, 2, 0, "DISPOSITIVOS CONHECIDOS", attr_header)
    header = "%-6s %-28s %-24s %5s  %-6s" % ("SLAVE", "FUNCAO", "PAYLOAD", "QTD", "HA")
    safe_addstr(stdscr, 3, 0, header, curses.A_UNDERLINE)

    max_device_rows = max(3, (h - 8) // 2)
    row = 4
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
                         help="Caminho de um CSV onde cada evento e gravado "
                              "conforme acontece (anexa se ja existir)")
    args = parser.parse_args()

    ser = serial.Serial(args.port, args.baudrate, parity=args.parity,
                         stopbits=args.stopbits, timeout=0.01)
    silence = max(char_time_seconds(args.baudrate, 8, args.parity, args.stopbits) * 3.5, 0.005)
    port_desc = "%s @ %s bps" % (args.port, args.baudrate)

    log_file = None
    log = None
    if args.log:
        log_file, log_writer = open_log(args.log)
        log = (log_file, log_writer)

    try:
        curses.wrapper(run, ser, silence, port_desc, log)
    finally:
        ser.close()
        if log_file is not None:
            log_file.close()


if __name__ == '__main__':
    main()
