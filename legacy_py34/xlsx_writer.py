# -*- coding: utf-8 -*-
"""Escritor minimo de planilhas .xlsx, sem dependencias externas.

O formato .xlsx (Office Open XML) e apenas um .zip com alguns arquivos
XML dentro. Este modulo monta esses arquivos na mao usando so a
biblioteca padrao (zipfile + escape de XML), sem precisar de openpyxl
nem de nada instalado via pip -- coerente com o resto do projeto, que
evita depender de internet/pip na BeagleBone (mesmo motivo de o
pyserial estar vendorizado em vez de instalado).

Suporta so o necessario para uma planilha de log de eventos: uma unica
aba, celulas de texto (inline strings, sem tabela de strings
compartilhadas) e numeros. Nao suporta formulas, formatacao, multiplas
abas, etc.

Uso:
    from xlsx_writer import write_xlsx
    write_xlsx('eventos.xlsx', ['Hora', 'Tipo', 'Valor'], [
        ['10:00:00', 'DEFAULT', 42],
        ['10:00:05', 'MUDOU', 43],
    ])
"""
import zipfile
from xml.sax.saxutils import escape as xml_escape

CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
</Types>
"""

ROOT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>
"""

WORKBOOK_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>
"""

WORKBOOK_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
<sheets><sheet name="Eventos" sheetId="1" r:id="rId1"/></sheets>
</workbook>
"""


def _col_letter(index):
    """Converte indice de coluna (0-based) para letra do Excel (0 -> A, 25 -> Z, 26 -> AA)."""
    letters = ""
    n = index + 1
    while n > 0:
        n, rem = divmod(n - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def _cell_xml(col_index, row_index, value):
    ref = "%s%d" % (_col_letter(col_index), row_index)
    if isinstance(value, bool):
        # bool antes de (int, float): bool e subclasse de int em Python.
        text = "1" if value else "0"
        return '<c r="%s" t="b"><v>%s</v></c>' % (ref, text)
    if isinstance(value, (int, float)):
        return '<c r="%s"><v>%s</v></c>' % (ref, value)
    text = "" if value is None else str(value)
    return '<c r="%s" t="inlineStr"><is><t xml:space="preserve">%s</t></is></c>' % (
        ref, xml_escape(text))


def _row_xml(row_index, values):
    cells = "".join(_cell_xml(i, row_index, v) for i, v in enumerate(values))
    return '<row r="%d">%s</row>' % (row_index, cells)


def _sheet_xml(headers, rows):
    parts = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>']
    parts.append('<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">')
    parts.append('<sheetData>')
    parts.append(_row_xml(1, headers))
    for i, row in enumerate(rows):
        parts.append(_row_xml(i + 2, row))
    parts.append('</sheetData>')
    parts.append('</worksheet>')
    return "".join(parts)


def write_xlsx(path, headers, rows):
    """Escreve uma planilha .xlsx de uma aba so, com cabecalho + linhas.

    'headers' e uma lista de strings. 'rows' e uma lista de listas, uma
    por linha, com valores str/int/float. Sobrescreve 'path' se ja
    existir (nao da para "acrescentar" num .zip existente de forma
    simples e segura, entao a planilha inteira e reescrita a cada
    chamada -- para o volume de eventos de um barramento RS-485 isso e
    desprezivel)."""
    tmp_path = path + ".tmp"
    with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", CONTENT_TYPES)
        zf.writestr("_rels/.rels", ROOT_RELS)
        zf.writestr("xl/workbook.xml", WORKBOOK_XML)
        zf.writestr("xl/_rels/workbook.xml.rels", WORKBOOK_RELS)
        zf.writestr("xl/worksheets/sheet1.xml", _sheet_xml(headers, rows))
    import os
    os.replace(tmp_path, path)
