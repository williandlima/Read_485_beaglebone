#!/usr/bin/env python3
"""Diagnostica e corrige a pilha de drivers FTDI no Windows.

Conversores USB/RS-485 com VID:PID de OEM (o padrao aqui e 0856:AC15, do
Black Box SP390A-R2) nao constam nos arquivos .inf da FTDI, entao o Windows
nao vincula o driver sozinho. Quando a vinculacao e forcada pela interface do
Gerenciador de Dispositivos, e facil errar a camada: o driver de porta
(FTSER2K) acaba instalado direto sobre o no USB cru, sem o driver de
barramento (FTDIBUS) embaixo.

O resultado e uma porta COM que abre, aceita write() e reporta "funcionando
corretamente" -- mas nao emite nenhuma transferencia USB, porque o FTSER2K
sozinho nao fala USB. Nenhum byte chega ao chip e o LED de TX nunca acende.

A pilha correta tem duas camadas:

    USB\\VID_xxxx&PID_yyyy\\<serie>            -> Service FTDIBUS  (barramento)
      +- FTDIBUS\\VID_xxxx+PID_yyyy+<serie>A   -> Service FTSER2K  (porta COM)

Este script enumera os nos via PnP, aponta qual camada esta errada e refaz a
vinculacao chamando UpdateDriverForPlugAndPlayDevices (newdev.dll) com
INSTALLFLAG_FORCE, usando os .inf assinados que ja estao no DriverStore. A
assinatura digital e preservada -- o que se ignora e apenas a checagem de
compatibilidade de hardware ID.

Uso:
    python fix_ftdi_windows.py                 # diagnostica, corrige e verifica
    python fix_ftdi_windows.py --dry-run       # so diagnostica
    python fix_ftdi_windows.py --vid 0403 --pid 6001
    python fix_ftdi_windows.py --test COM8     # so o teste de loopback
"""

import argparse
import atexit
import ctypes
import glob
import json
import os
import subprocess
import sys
import tempfile
import time

VID_PADRAO = "0856"
PID_PADRAO = "AC15"

SERVICO_BARRAMENTO = "FTDIBUS"
SERVICO_PORTA = "FTSER2K"

INSTALLFLAG_FORCE = 0x00000001

PAYLOAD = b"\xAA\x55\x01\x02\x03\x04\xFF"

CAMINHO_LOG = os.path.join(tempfile.gettempdir(), "fix_ftdi_windows.log")


# ---------------------------------------------------------------- utilidades


class Tee:
    """Espelha a saida no console e num arquivo de log.

    A janela elevada aberta pelo UAC fecha assim que o script termina, entao
    sem o log o relatorio se perde antes de ser lido.
    """

    def __init__(self, *streams):
        self.streams = streams

    def write(self, dados):
        for s in self.streams:
            try:
                s.write(dados)
                s.flush()
            except Exception:
                pass

    def flush(self):
        for s in self.streams:
            try:
                s.flush()
            except Exception:
                pass


def iniciar_log():
    try:
        arquivo = open(CAMINHO_LOG, "w", encoding="utf-8", errors="replace")
    except Exception:
        return
    sys.stdout = Tee(sys.__stdout__, arquivo)
    sys.stderr = Tee(sys.__stderr__, arquivo)
    atexit.register(arquivo.close)


def pausar_ao_sair():
    """Segura a janela aberta para o relatorio poder ser lido."""
    print()
    print("Log salvo em: {}".format(CAMINHO_LOG))
    try:
        input("Pressione Enter para fechar esta janela...")
    except Exception:
        pass


def secao(titulo):
    print()
    print("=" * 68)
    print(titulo)
    print("=" * 68)


def exigir_windows():
    if os.name != "nt":
        print("Este script so funciona no Windows.")
        sys.exit(1)


def e_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def reabrir_como_admin():
    """Relanca o script com elevacao (dispara o prompt do UAC).

    O filho recebe --elevated para saber que precisa segurar a janela aberta
    no fim -- do contrario o console some junto com o relatorio.
    """
    argumentos = list(sys.argv) + ["--elevated"]
    params = " ".join('"{}"'.format(a) for a in argumentos)
    rc = ctypes.windll.shell32.ShellExecuteW(
        None, "runas", sys.executable, params, None, 1
    )
    if rc <= 32:
        print("Falha ao solicitar elevacao (codigo {}).".format(rc))
        if rc == 5:
            print("O prompt do UAC foi recusado.")
        print()
        print("Alternativa: abra o PowerShell como Administrador")
        print("(Win -> digite powershell -> botao direito -> Executar como")
        print("administrador) e rode o script por la.")
        sys.exit(1)
    print("Uma janela elevada foi aberta -- aceite o prompt do UAC.")
    print("O relatorio aparece la e tambem fica salvo em:")
    print("  {}".format(CAMINHO_LOG))
    sys.exit(0)


def powershell(script):
    """Roda um trecho de PowerShell e devolve a saida como texto."""
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
    )
    return proc.stdout.strip()


def pnputil(*args):
    proc = subprocess.run(
        ["pnputil"] + list(args), capture_output=True, text=True
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


# ------------------------------------------------------------- enumeracao PnP


def enumerar(vid, pid):
    """Devolve os nos PnP que casam com o VID/PID informado."""
    filtro = "*VID_{}*PID_{}*".format(vid, pid)
    script = (
        "Get-PnpDevice | Where-Object {{ $_.InstanceId -like '{}' }} | "
        "Select-Object FriendlyName,InstanceId,Class,Service,Status,Present,"
        "HardwareID | ConvertTo-Json -Depth 4"
    ).format(filtro)

    saida = powershell(script)
    if not saida:
        return []

    try:
        dados = json.loads(saida)
    except json.JSONDecodeError:
        print("Nao consegui interpretar a saida do PowerShell:")
        print(saida)
        return []

    if isinstance(dados, dict):
        dados = [dados]

    for d in dados:
        hw = d.get("HardwareID") or []
        if isinstance(hw, str):
            hw = [hw]
        d["HardwareID"] = hw
    return dados


def classificar(dispositivos):
    """Separa os nos em camada de barramento (USB\\) e camada de porta."""
    barramento, portas, outros = [], [], []
    for d in dispositivos:
        iid = (d.get("InstanceId") or "").upper()
        if iid.startswith("USB\\"):
            barramento.append(d)
        elif iid.startswith("FTDIBUS\\"):
            portas.append(d)
        else:
            outros.append(d)
    return barramento, portas, outros


def mostrar(dispositivos):
    if not dispositivos:
        print("  (nenhum)")
        return
    for d in dispositivos:
        presente = "presente" if d.get("Present") else "ausente"
        print("  {}".format(d.get("FriendlyName") or "?"))
        print("    InstanceId : {}".format(d.get("InstanceId")))
        print("    Class      : {}".format(d.get("Class")))
        print("    Service    : {}".format(d.get("Service") or "(nenhum)"))
        print("    Status     : {} / {}".format(d.get("Status"), presente))


def diagnosticar(barramento, portas):
    """Avalia cada camada e devolve (lista_de_problemas, tudo_ok)."""
    problemas = []

    presentes = [d for d in barramento if d.get("Present")]
    if not presentes:
        problemas.append(
            "Nenhum no USB do conversor esta presente. "
            "Conecte o conversor antes de rodar o script."
        )
        return problemas, False

    for d in presentes:
        servico = (d.get("Service") or "").upper()
        if servico != SERVICO_BARRAMENTO:
            problemas.append(
                "Camada de barramento errada em {}: Service={} (esperado {}).".format(
                    d.get("InstanceId"), servico or "nenhum", SERVICO_BARRAMENTO
                )
            )

    portas_presentes = [d for d in portas if d.get("Present")]
    if not portas_presentes:
        problemas.append(
            "Nenhum no de porta sob FTDIBUS\\. A camada de porta nao existe."
        )
    for d in portas_presentes:
        servico = (d.get("Service") or "").upper()
        if servico != SERVICO_PORTA:
            problemas.append(
                "Camada de porta errada em {}: Service={} (esperado {}).".format(
                    d.get("InstanceId"), servico or "nenhum", SERVICO_PORTA
                )
            )

    # Uma porta COM pendurada direto no no USB e o sintoma classico.
    for d in presentes:
        if (d.get("Class") or "").upper() == "PORTS":
            problemas.append(
                "A porta COM esta vinculada direto ao no USB ({}). "
                "O FTSER2K nao fala USB: a porta abre, aceita write() e nao "
                "transmite nada.".format(d.get("InstanceId"))
            )

    return problemas, not problemas


# ------------------------------------------------------------ correcao da pilha


def localizar_infs():
    """Acha ftdibus.inf e ftdiport.inf no DriverStore."""
    raiz = os.path.join(
        os.environ.get("SystemRoot", r"C:\Windows"),
        "System32",
        "DriverStore",
        "FileRepository",
    )
    achados = {}
    for nome in ("ftdibus.inf", "ftdiport.inf"):
        padrao = os.path.join(raiz, nome.replace(".inf", ".inf_*"), nome)
        candidatos = sorted(glob.glob(padrao))
        if candidatos:
            achados[nome] = candidatos[-1]
    return achados


def forcar_driver(hardware_id, caminho_inf):
    """Tenta vincular um .inf pelo hardware ID.

    So funciona quando o .inf realmente lista o ID: INSTALLFLAG_FORCE dispensa
    o ranking de "melhor driver", nao a checagem de compatibilidade. Para um
    VID:PID de OEM ausente do .inf isto falha, e a saida cai em
    instalar_via_inf(), que seleciona o no de driver diretamente.
    """
    from ctypes import wintypes

    newdev = ctypes.WinDLL("newdev.dll", use_last_error=True)
    fn = newdev.UpdateDriverForPlugAndPlayDevicesW
    fn.argtypes = [
        wintypes.HWND,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.BOOL),
    ]
    fn.restype = wintypes.BOOL

    reiniciar = wintypes.BOOL(False)
    ok = fn(None, hardware_id, caminho_inf, INSTALLFLAG_FORCE, ctypes.byref(reiniciar))
    erro = 0 if ok else ctypes.get_last_error()
    return bool(ok), erro, bool(reiniciar.value)


# --------------------------------------------------- instalacao por no de driver
#
# Este e o caminho que a opcao "Deixe-me escolher entre uma lista de drivers"
# usa por baixo. Em vez de procurar no .inf um driver que case com o hardware
# ID do dispositivo, ele enumera os nos de driver de um .inf especifico
# (DI_ENUMSINGLEINF), seleciona um a dedo e manda instalar. Como nao ha etapa
# de casamento de ID, funciona com VID:PID de OEM ausentes do .inf -- e os
# binarios continuam sendo os assinados que ja estao no DriverStore.

MAX_PATH = 260
LINE_LEN = 256

DIGCF_PRESENT = 0x00000002
DIGCF_ALLCLASSES = 0x00000004

SPDIT_CLASSDRIVER = 0x00000001

DI_ENUMSINGLEINF = 0x00010000
DI_FLAGSEX_ALLOWEXCLUDEDDRVS = 0x00000800

_api_cache = {}


def _api():
    """Carrega setupapi/newdev e as estruturas necessarias (so no Windows)."""
    if _api_cache:
        return _api_cache

    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [
            ("Data1", ctypes.c_ulong),
            ("Data2", ctypes.c_ushort),
            ("Data3", ctypes.c_ushort),
            ("Data4", ctypes.c_ubyte * 8),
        ]

    class SP_DEVINFO_DATA(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("ClassGuid", GUID),
            ("DevInst", wintypes.DWORD),
            ("Reserved", ctypes.c_size_t),
        ]

    class SP_DRVINFO_DATA_V2_W(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("DriverType", wintypes.DWORD),
            ("Reserved", ctypes.c_size_t),
            ("Description", wintypes.WCHAR * LINE_LEN),
            ("MfgName", wintypes.WCHAR * LINE_LEN),
            ("ProviderName", wintypes.WCHAR * LINE_LEN),
            ("DriverDate", wintypes.FILETIME),
            ("DriverVersion", ctypes.c_ulonglong),
        ]

    class SP_DEVINSTALL_PARAMS_W(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("Flags", wintypes.DWORD),
            ("FlagsEx", wintypes.DWORD),
            ("hwndParent", wintypes.HWND),
            ("InstallMsgHandler", ctypes.c_void_p),
            ("InstallMsgHandlerContext", ctypes.c_void_p),
            ("FileQueue", ctypes.c_void_p),
            ("ClassInstallReserved", ctypes.c_size_t),
            ("Reserved", wintypes.DWORD),
            ("DriverPath", wintypes.WCHAR * MAX_PATH),
        ]

    setupapi = ctypes.WinDLL("setupapi.dll", use_last_error=True)
    newdev = ctypes.WinDLL("newdev.dll", use_last_error=True)

    setupapi.SetupDiGetClassDevsW.restype = ctypes.c_void_p
    setupapi.SetupDiGetClassDevsW.argtypes = [
        ctypes.c_void_p, wintypes.LPCWSTR, wintypes.HWND, wintypes.DWORD,
    ]
    setupapi.SetupDiEnumDeviceInfo.argtypes = [
        ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(SP_DEVINFO_DATA),
    ]
    setupapi.SetupDiGetDeviceInstanceIdW.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(SP_DEVINFO_DATA), wintypes.LPWSTR,
        wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
    ]
    setupapi.SetupDiGetDeviceInstallParamsW.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(SP_DEVINFO_DATA),
        ctypes.POINTER(SP_DEVINSTALL_PARAMS_W),
    ]
    setupapi.SetupDiSetDeviceInstallParamsW.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(SP_DEVINFO_DATA),
        ctypes.POINTER(SP_DEVINSTALL_PARAMS_W),
    ]
    setupapi.SetupDiBuildDriverInfoList.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(SP_DEVINFO_DATA), wintypes.DWORD,
    ]
    setupapi.SetupDiEnumDriverInfoW.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(SP_DEVINFO_DATA), wintypes.DWORD,
        wintypes.DWORD, ctypes.POINTER(SP_DRVINFO_DATA_V2_W),
    ]
    setupapi.SetupDiSetSelectedDriverW.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(SP_DEVINFO_DATA),
        ctypes.POINTER(SP_DRVINFO_DATA_V2_W),
    ]
    setupapi.SetupDiDestroyDriverInfoList.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(SP_DEVINFO_DATA), wintypes.DWORD,
    ]
    setupapi.SetupDiDestroyDeviceInfoList.argtypes = [ctypes.c_void_p]

    newdev.DiInstallDevice.argtypes = [
        wintypes.HWND, ctypes.c_void_p, ctypes.POINTER(SP_DEVINFO_DATA),
        ctypes.POINTER(SP_DRVINFO_DATA_V2_W), wintypes.DWORD,
        ctypes.POINTER(wintypes.BOOL),
    ]
    newdev.DiInstallDevice.restype = wintypes.BOOL

    _api_cache.update(
        setupapi=setupapi,
        newdev=newdev,
        SP_DEVINFO_DATA=SP_DEVINFO_DATA,
        SP_DRVINFO_DATA_V2_W=SP_DRVINFO_DATA_V2_W,
        SP_DEVINSTALL_PARAMS_W=SP_DEVINSTALL_PARAMS_W,
        wintypes=wintypes,
    )
    return _api_cache


def _achar_devinfo(api, instance_id):
    """Localiza o dispositivo pelo InstanceId. Devolve (handle, devinfo)."""
    setupapi = api["setupapi"]
    SP_DEVINFO_DATA = api["SP_DEVINFO_DATA"]
    wintypes = api["wintypes"]

    handle = setupapi.SetupDiGetClassDevsW(
        None, None, None, DIGCF_PRESENT | DIGCF_ALLCLASSES
    )
    if handle in (None, 0) or handle == ctypes.c_void_p(-1).value:
        return None, None

    alvo = instance_id.upper()
    indice = 0
    while True:
        info = SP_DEVINFO_DATA()
        info.cbSize = ctypes.sizeof(SP_DEVINFO_DATA)
        if not setupapi.SetupDiEnumDeviceInfo(handle, indice, ctypes.byref(info)):
            break
        indice += 1

        buf = ctypes.create_unicode_buffer(MAX_PATH)
        necessario = wintypes.DWORD(0)
        if not setupapi.SetupDiGetDeviceInstanceIdW(
            handle, ctypes.byref(info), buf, MAX_PATH, ctypes.byref(necessario)
        ):
            continue
        if buf.value.upper() == alvo:
            return handle, info

    setupapi.SetupDiDestroyDeviceInfoList(handle)
    return None, None


def instalar_via_inf(instance_id, caminho_inf, preferencia=None):
    """Instala um no de driver de um .inf especifico no dispositivo dado.

    Replica o caminho "Deixe-me escolher entre uma lista de drivers": nao ha
    casamento de hardware ID, entao funciona com VID:PID de OEM.
    Devolve (ok, mensagem).
    """
    api = _api()
    setupapi = api["setupapi"]
    newdev = api["newdev"]
    SP_DRVINFO = api["SP_DRVINFO_DATA_V2_W"]
    SP_PARAMS = api["SP_DEVINSTALL_PARAMS_W"]
    wintypes = api["wintypes"]

    handle, info = _achar_devinfo(api, instance_id)
    if handle is None:
        return False, "dispositivo {} nao encontrado (esta conectado?)".format(instance_id)

    try:
        # Restringe a busca de drivers a este unico .inf.
        params = SP_PARAMS()
        params.cbSize = ctypes.sizeof(SP_PARAMS)
        if not setupapi.SetupDiGetDeviceInstallParamsW(
            handle, ctypes.byref(info), ctypes.byref(params)
        ):
            return False, "SetupDiGetDeviceInstallParams falhou (erro {})".format(
                ctypes.get_last_error())

        params.Flags |= DI_ENUMSINGLEINF
        params.FlagsEx |= DI_FLAGSEX_ALLOWEXCLUDEDDRVS
        params.DriverPath = caminho_inf
        if not setupapi.SetupDiSetDeviceInstallParamsW(
            handle, ctypes.byref(info), ctypes.byref(params)
        ):
            return False, "SetupDiSetDeviceInstallParams falhou (erro {})".format(
                ctypes.get_last_error())

        if not setupapi.SetupDiBuildDriverInfoList(
            handle, ctypes.byref(info), SPDIT_CLASSDRIVER
        ):
            return False, "SetupDiBuildDriverInfoList falhou (erro {})".format(
                ctypes.get_last_error())

        # Enumera os nos de driver do .inf e escolhe o desejado.
        escolhido = None
        disponiveis = []
        indice = 0
        while True:
            drv = SP_DRVINFO()
            drv.cbSize = ctypes.sizeof(SP_DRVINFO)
            if not setupapi.SetupDiEnumDriverInfoW(
                handle, ctypes.byref(info), SPDIT_CLASSDRIVER, indice, ctypes.byref(drv)
            ):
                break
            indice += 1
            disponiveis.append(drv.Description)
            if escolhido is None:
                if preferencia is None or drv.Description.strip().lower() == preferencia.lower():
                    escolhido = drv

        if escolhido is None and disponiveis:
            # A descricao preferida nao existe neste .inf; usa o primeiro no.
            drv = SP_DRVINFO()
            drv.cbSize = ctypes.sizeof(SP_DRVINFO)
            if setupapi.SetupDiEnumDriverInfoW(
                handle, ctypes.byref(info), SPDIT_CLASSDRIVER, 0, ctypes.byref(drv)
            ):
                escolhido = drv

        if escolhido is None:
            return False, "nenhum no de driver em {}".format(os.path.basename(caminho_inf))

        if not setupapi.SetupDiSetSelectedDriverW(
            handle, ctypes.byref(info), ctypes.byref(escolhido)
        ):
            return False, "SetupDiSetSelectedDriver falhou (erro {})".format(
                ctypes.get_last_error())

        reiniciar = wintypes.BOOL(False)
        ok = newdev.DiInstallDevice(
            None, handle, ctypes.byref(info), ctypes.byref(escolhido), 0,
            ctypes.byref(reiniciar),
        )
        if not ok:
            return False, "DiInstallDevice falhou (erro {}); nos disponiveis: {}".format(
                ctypes.get_last_error(), ", ".join(disponiveis) or "nenhum")

        return True, 'instalado "{}"'.format(escolhido.Description.strip())
    finally:
        try:
            setupapi.SetupDiDestroyDriverInfoList(
                handle, ctypes.byref(info), SPDIT_CLASSDRIVER
            )
        except Exception:
            pass
        setupapi.SetupDiDestroyDeviceInfoList(handle)


def hardware_id_base(dispositivo, prefixo):
    """Escolhe o hardware ID mais generico que comeca com o prefixo dado."""
    candidatos = [
        h for h in dispositivo.get("HardwareID", []) if h.upper().startswith(prefixo)
    ]
    if not candidatos:
        return None
    # O mais curto e o menos especifico (sem &REV_, sem numero de serie).
    return sorted(candidatos, key=len)[0]


def rescan():
    pnputil("/scan-devices")
    time.sleep(2)


def vincular(instance_id, caminho_inf, hwid, preferencia):
    """Vincula um .inf a um dispositivo, tentando os dois caminhos disponiveis.

    Primeiro o casamento por hardware ID (rapido, mas so funciona se o .inf
    listar o ID); depois a selecao direta do no de driver, que e o que resolve
    para VID:PID de OEM.
    """
    if hwid:
        ok, erro, _ = forcar_driver(hwid, caminho_inf)
        if ok:
            return True, "vinculado por hardware ID"
        if erro == 259:  # ERROR_NO_MORE_ITEMS: o ID nao consta no .inf
            print("    (o .inf nao lista {}; selecionando o no de driver)".format(hwid))
        else:
            print("    (casamento por hardware ID falhou, erro {})".format(erro))

    return instalar_via_inf(instance_id, caminho_inf, preferencia)


def esperar_no_de_porta(vid, pid, tentativas=5):
    """Aguarda o filho FTDIBUS\\ aparecer depois que o barramento sobe."""
    for _ in range(tentativas):
        _, portas, _ = classificar(enumerar(vid, pid))
        presentes = [d for d in portas if d.get("Present")]
        if presentes:
            return presentes
        rescan()
    return []


def corrigir(vid, pid, infs):
    """Refaz as duas camadas da pilha, de baixo para cima."""
    ok_total = True

    if "ftdibus.inf" not in infs or "ftdiport.inf" not in infs:
        print("Faltam .inf da FTDI no DriverStore.")
        print("Instale o driver VCP da FTDI (ou o da Black Box) e rode de novo.")
        return False

    # --- camada 1: barramento -------------------------------------------
    barramento, _, _ = classificar(enumerar(vid, pid))
    presentes = [d for d in barramento if d.get("Present")]

    if not presentes:
        print("Conversor nao esta presente. Conecte-o e rode de novo.")
        return False

    for d in presentes:
        instance_id = d.get("InstanceId")
        servico = (d.get("Service") or "").upper()
        if servico == SERVICO_BARRAMENTO:
            print("Camada de barramento ja correta em {}.".format(instance_id))
            continue

        print("Instalando ftdibus.inf em {} ...".format(instance_id))
        ok, msg = vincular(
            instance_id, infs["ftdibus.inf"],
            hardware_id_base(d, "USB\\"), "USB Serial Converter",
        )
        print("  {}".format(msg))
        ok_total = ok_total and ok

    rescan()

    # --- camada 2: porta COM --------------------------------------------
    portas_presentes = esperar_no_de_porta(vid, pid)
    if not portas_presentes:
        print("O no de porta sob FTDIBUS\\ nao apareceu.")
        print("Desconecte e reconecte o conversor, depois rode de novo.")
        return False

    for d in portas_presentes:
        instance_id = d.get("InstanceId")
        servico = (d.get("Service") or "").upper()
        if servico == SERVICO_PORTA:
            print("Camada de porta ja correta em {}.".format(instance_id))
            continue

        print("Instalando ftdiport.inf em {} ...".format(instance_id))
        ok, msg = vincular(
            instance_id, infs["ftdiport.inf"],
            hardware_id_base(d, "FTDIBUS\\"), "USB Serial Port",
        )
        print("  {}".format(msg))
        ok_total = ok_total and ok

    rescan()
    return ok_total


def porta_com(vid, pid):
    """Devolve o nome da porta COM criada pela pilha, se houver."""
    dispositivos = enumerar(vid, pid)
    for d in dispositivos:
        if not d.get("Present"):
            continue
        if (d.get("Class") or "").upper() != "PORTS":
            continue
        nome = d.get("FriendlyName") or ""
        if "(COM" in nome:
            numero = nome.split("(COM")[1].split(")")[0]
            return "COM" + numero
    return None


# ---------------------------------------------------------- teste de loopback


def teste_loopback(porta, baud=9600):
    """Escreve o payload e confere o eco. Exige jumper A-A / B-B no conversor."""
    try:
        import serial
    except ImportError:
        print("pyserial nao instalado neste Python. Rode: pip install pyserial")
        return False

    print("Abrindo {} a {} bps...".format(porta, baud))
    try:
        with serial.Serial(porta, baud, timeout=0.5) as ser:
            for rts in (False, True):
                ser.rts = rts
                time.sleep(0.02)
                ser.reset_input_buffer()
                ser.write(PAYLOAD)
                time.sleep(0.05)
                eco = ser.read(len(PAYLOAD))
                print("  RTS={}: recebido {} byte(s) {}".format(
                    rts, len(eco), eco.hex(" ") if eco else ""))
                if eco == PAYLOAD:
                    print("  ECO OK -- a pilha esta transmitindo de verdade.")
                    return True
    except Exception as e:
        print("  erro: {}".format(e))
        return False

    print("  sem eco. Se o LED TD piscou, a pilha esta OK e falta o jumper")
    print("  (TDA- em RDA-, TDB+ em RDB+) ou o Echo do conversor esta desligado.")
    return False


# ---------------------------------------------------------------------- main


def main():
    p = argparse.ArgumentParser(
        description="Diagnostica e corrige a pilha de drivers FTDI no Windows."
    )
    p.add_argument("--vid", default=VID_PADRAO, help="VID em hex (padrao: %(default)s)")
    p.add_argument("--pid", default=PID_PADRAO, help="PID em hex (padrao: %(default)s)")
    p.add_argument("--dry-run", action="store_true", help="so diagnostica, nao corrige")
    p.add_argument("--test", metavar="COMx", help="so roda o teste de loopback nessa porta")
    p.add_argument("--baud", type=int, default=9600, help="baud do teste (padrao: %(default)s)")
    p.add_argument("--elevated", action="store_true", help=argparse.SUPPRESS)
    args = p.parse_args()

    exigir_windows()

    # Relanca antes de abrir o log, para que so o processo que faz o trabalho
    # seja dono do arquivo.
    precisa_elevar = not args.test and not args.dry_run and not e_admin()
    if precisa_elevar:
        print("Preciso de privilegio de administrador para religar os drivers.")
        reabrir_como_admin()

    iniciar_log()

    # A janela aberta pelo UAC fecha sozinha no fim; sem isso o relatorio some.
    if args.elevated:
        atexit.register(pausar_ao_sair)

    if args.test:
        secao("TESTE DE LOOPBACK")
        sys.exit(0 if teste_loopback(args.test, args.baud) else 1)

    vid = args.vid.upper().replace("0X", "")
    pid = args.pid.upper().replace("0X", "")

    secao("ESTADO ATUAL DA PILHA  (VID_{} PID_{})".format(vid, pid))
    dispositivos = enumerar(vid, pid)
    if not dispositivos:
        print("Nenhum dispositivo com esse VID:PID foi encontrado.")
        print("Conecte o conversor, ou informe outro par com --vid/--pid.")
        sys.exit(1)

    barramento, portas, outros = classificar(dispositivos)
    print("\nCamada de barramento (nos USB\\):")
    mostrar(barramento)
    print("\nCamada de porta (nos FTDIBUS\\):")
    mostrar(portas)
    if outros:
        print("\nOutros nos:")
        mostrar(outros)

    secao("DIAGNOSTICO")
    problemas, tudo_ok = diagnosticar(barramento, portas)
    if tudo_ok:
        print("A pilha esta correta: FTDIBUS no no USB e FTSER2K sob FTDIBUS\\.")
    else:
        for i, msg in enumerate(problemas, 1):
            print("{}. {}".format(i, msg))

    if args.dry_run:
        sys.exit(0 if tudo_ok else 1)

    if not tudo_ok:
        secao("CORRIGINDO")
        infs = localizar_infs()
        for nome, caminho in infs.items():
            print("{}: {}".format(nome, caminho))
        if not infs:
            print("Nenhum .inf da FTDI no DriverStore.")
            print("Instale o driver VCP da FTDI (ou o da Black Box) e rode de novo.")
            sys.exit(1)
        print()
        corrigir(vid, pid, infs)

        secao("ESTADO APOS A CORRECAO")
        dispositivos = enumerar(vid, pid)
        barramento, portas, _ = classificar(dispositivos)
        print("\nCamada de barramento (nos USB\\):")
        mostrar(barramento)
        print("\nCamada de porta (nos FTDIBUS\\):")
        mostrar(portas)

        problemas, tudo_ok = diagnosticar(barramento, portas)
        print()
        if tudo_ok:
            print("Pilha corrigida.")
        else:
            for i, msg in enumerate(problemas, 1):
                print("{}. {}".format(i, msg))
            print("\nSe algo persistir, desconecte e reconecte o conversor e rode de novo.")

    com = porta_com(vid, pid)
    if com:
        secao("TESTE DE LOOPBACK EM {}".format(com))
        print("Olhe o LED TD do conversor durante o teste.\n")
        teste_loopback(com, args.baud)
    else:
        print("\nNenhuma porta COM ativa foi encontrada para testar.")

    sys.exit(0 if tudo_ok else 1)


if __name__ == "__main__":
    main()
