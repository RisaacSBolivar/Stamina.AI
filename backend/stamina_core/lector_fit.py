"""
Lector propio de los mensajes `record` de un .FIT.

`fitparse` decodifica el archivo entero, mensaje a mensaje y campo a campo, con
objetos de Python para cada valor. Era el 92 % del tiempo de `procesar_fit`: en
un servidor con una fracción de CPU, leer 12 h de historial costaba minutos,
tanto al subir los `.FIT` como al bajarlos de Garmin. Aquí solo se decodifica lo
que usa `procesar_fit` —los campos de `CAMPOS_FIT` de los mensajes `record`— y
el resto del archivo se recorre sin interpretarlo.

La salida es **la misma** que `fitparse.FitFile(...).get_messages("record")`
reducida a esos campos: los valores inválidos pasan a None, se aplican la misma
escala y el mismo desfase, se reconstruyen igual las marcas de tiempo
comprimidas y los componentes (`speed` → `enhanced_speed`, `altitude` →
`enhanced_altitude`) y un CRC que no cuadra rechaza el archivo. Verificado
registro a registro con los 492 `.FIT` del autor, los de la demo y los
sintéticos (686 archivos, 2026-09-26); `tests/test_lector_fit.py` lo vuelve a
comparar con fitparse en cada `make test`.

Lo que no replica, lo delega. Un archivo con campos de desarrollador (los de
las apps de Connect IQ) lanza `DelegarEnFitparse`: fitparse los resuelve con un
registro global que arrastra de archivos anteriores, y copiar eso sería copiar
un defecto. `procesar_fit` lee entonces el archivo con fitparse, como antes.
"""

from __future__ import annotations

import struct
from datetime import datetime, timedelta

from .config import CAMPOS_FIT

# fitparse devuelve las fechas como datetime ingenuo en UTC, contadas desde la
# época FIT; por debajo de 0x10000000 son tiempo relativo y deja el entero.
EPOCA_FIT = datetime(1989, 12, 31)
MINIMO_FECHA_ABSOLUTA = 0x10000000

MENSAJE_RECORD = 20
CAMPO_TIMESTAMP = 253

T_STRING = 0x07
T_BYTE = 0x0D
NAN = object()  # marca de los tipos flotantes: su valor inválido es NaN

# Tipo base -> (formato de struct, tamaño, valor inválido). Los mismos de fitparse.
TIPOS_BASE = {
    0x00: ("B", 1, 0xFF),  # enum
    0x01: ("b", 1, 0x7F),  # sint8
    0x02: ("B", 1, 0xFF),  # uint8
    0x83: ("h", 2, 0x7FFF),  # sint16
    0x84: ("H", 2, 0xFFFF),  # uint16
    0x85: ("i", 4, 0x7FFFFFFF),  # sint32
    0x86: ("I", 4, 0xFFFFFFFF),  # uint32
    T_STRING: ("s", 1, None),
    0x88: ("f", 4, NAN),  # float32
    0x89: ("d", 8, NAN),  # float64
    0x0A: ("B", 1, 0),  # uint8z
    0x8B: ("H", 2, 0),  # uint16z
    0x8C: ("I", 4, 0),  # uint32z
    T_BYTE: ("B", 1, None),  # inválido si todos sus bytes son 0xFF
    0x8E: ("q", 8, 0x7FFFFFFFFFFFFFFF),  # sint64
    0x8F: ("Q", 8, 0xFFFFFFFFFFFFFFFF),  # uint64
    0x90: ("Q", 8, 0),  # uint64z
}

# Campos de `record` que se leen: número -> (nombre, escala, desfase). Perfil FIT.
CAMPOS_RECORD = {
    CAMPO_TIMESTAMP: ("timestamp", None, None),
    5: ("distance", 100, None),
    3: ("heart_rate", None, None),
    4: ("cadence", None, None),
    73: ("enhanced_speed", 1000, None),
    78: ("enhanced_altitude", 5, 500),
    13: ("temperature", None, None),
}

# Campos que no se leen pero cuyos componentes sí: número -> componentes, cada uno
# (nombre, número del campo destino, bits, desplazamiento de bits, escala, desfase,
# acumula). Relojes antiguos solo graban `speed` y `altitude`, y fitparse les saca
# el `enhanced_*`; `compressed_speed_distance` trae una distancia acumulada.
COMPONENTES_RECORD = {
    6: (("enhanced_speed", 73, 16, 0, 1000, None, False),),
    2: (("enhanced_altitude", 78, 16, 0, 5, 500, False),),
    8: (("speed", 6, 12, 0, 100, None, False), ("distance", 5, 12, 12, 16, None, True)),
}

INTERESAN = frozenset(CAMPOS_FIT)


def _tabla_crc() -> tuple[int, ...]:
    # El CRC del protocolo FIT es el CRC-16 de polinomio 0x8005 reflejado (0xA001).
    # `entrenamiento.crc_fit` lo calcula de a medio byte; con una tabla de un byte
    # entero sale lo mismo en la mitad de pasos, y aquí se pasa por cada byte leído.
    tabla = []
    for byte in range(256):
        crc = byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
        tabla.append(crc)
    return tuple(tabla)


TABLA_CRC = _tabla_crc()


def crc(datos: bytes, valor: int = 0) -> int:
    """CRC de 16 bits del protocolo FIT (el mismo que `entrenamiento.crc_fit`)."""
    tabla = TABLA_CRC
    for byte in datos:
        valor = (valor >> 8) ^ tabla[(valor ^ byte) & 0xFF]
    return valor


class FitIlegible(ValueError):
    """El archivo no es un .FIT válido: fitparse también lo rechazaría."""


class DelegarEnFitparse(Exception):
    """Algo que este lector no replica a propósito: que lo lea fitparse."""


def leer_records(datos: bytes) -> list[dict]:
    """
    Los mensajes `record` del .FIT, cada uno como dict con los campos de `CAMPOS_FIT`.

    Igual que en fitparse, un campo definido pero con valor inválido aparece con
    None, y uno que el reloj no graba no aparece.
    """
    registros: list[dict] = []
    total = len(datos)
    pos = 0
    while True:
        pos = _leer_archivo(datos, pos, registros)
        # Varios .FIT pueden venir encadenados en el mismo archivo.
        if pos >= total:
            return registros


def _leer_archivo(datos: bytes, pos: int, registros: list[dict]) -> int:
    """Lee un .FIT (cabecera, mensajes y CRC) desde `pos` y devuelve dónde acaba."""
    if len(datos) - pos < 12 or datos[pos + 8 : pos + 12] != b".FIT":
        raise FitIlegible("cabecera de .FIT inválida")
    tam_cabecera, _, _, tam_datos = struct.unpack_from("<2BHI", datos, pos)
    valor_crc = crc(datos[pos : pos + 12])
    inicio = pos + 12
    extra = tam_cabecera - 12
    if extra > 0:
        if extra < 2:
            raise FitIlegible("cabecera de tamaño irregular")
        (crc_cabecera,) = struct.unpack_from("<H", datos, inicio)
        if crc_cabecera not in (0, valor_crc):
            raise FitIlegible("el CRC de la cabecera no cuadra")
        valor_crc = crc(datos[inicio : inicio + extra], valor_crc)
        inicio += extra
    fin = inicio + tam_datos
    if fin + 2 > len(datos):
        raise FitIlegible("archivo truncado")

    # Por tipo local de mensaje: (número global, struct, plan, posición del timestamp).
    locales: dict[int, tuple] = {}
    acumulados: dict[int, int] = {}
    ultimo_timestamp = 0
    p = inicio
    while p < fin:
        cabecera = datos[p]
        p += 1
        if cabecera & 0x80:  # cabecera de timestamp comprimido
            local, desfase = (cabecera >> 5) & 0x3, cabecera & 0x1F
        elif cabecera & 0x40:  # mensaje de definición
            p = _leer_definicion(datos, p, cabecera, locales, acumulados)
            continue
        else:
            local, desfase = cabecera & 0xF, None

        definicion = locales.get(local)
        if definicion is None:
            raise FitIlegible("mensaje de datos sin definición")
        numero, estructura, plan, pos_timestamp = definicion
        valores = estructura.unpack_from(datos, p)
        p += estructura.size

        if numero != MENSAJE_RECORD:
            # De los demás mensajes solo importa su timestamp: es la base de los
            # comprimidos que vengan después, sean del tipo que sean.
            if pos_timestamp is not None:
                crudo = _valor(valores, *pos_timestamp)
                if crudo is not None:
                    ultimo_timestamp = crudo
            if desfase is not None:
                ultimo_timestamp = _acumular(desfase, ultimo_timestamp, 5)
            continue

        registro: dict = {}
        for indice, cantidad, base, numero_campo, campo, componentes in plan:
            crudo = _valor(valores, indice, cantidad, base)
            if componentes is not None:
                _expandir(crudo, componentes, acumulados, registro)
            if numero_campo == CAMPO_TIMESTAMP and crudo is not None:
                ultimo_timestamp = crudo
            if campo is not None:
                nombre, escala, desplazamiento = campo
                valor = _escalar(crudo, escala, desplazamiento)
                registro[nombre] = _fecha(valor) if numero_campo == CAMPO_TIMESTAMP else valor
        if desfase is not None:
            ultimo_timestamp = _acumular(desfase, ultimo_timestamp, 5)
            registro["timestamp"] = _fecha(ultimo_timestamp)
        registros.append(registro)

    if p != fin:
        raise FitIlegible("los mensajes no cuadran con el tamaño declarado")
    (crc_archivo,) = struct.unpack_from("<H", datos, fin)
    if crc(datos[inicio:fin], valor_crc) != crc_archivo:
        raise FitIlegible("el CRC del archivo no cuadra")
    return fin + 2


def _leer_definicion(datos, p, cabecera, locales, acumulados) -> int:
    """Registra una definición y prepara cómo leer sus mensajes de datos."""
    endian = ">" if datos[p + 1] else "<"
    numero, n_campos = struct.unpack_from(endian + "HB", datos, p + 2)
    p += 5

    formato = [endian]
    plan = []
    pos_timestamp = None
    indice = 0
    for _ in range(n_campos):
        numero_campo, tamano, base = datos[p], datos[p + 1], datos[p + 2]
        p += 3
        if base not in TIPOS_BASE:
            base = T_BYTE  # fitparse trata así los tipos que no conoce
        letra, tam_base, _ = TIPOS_BASE[base]
        if tamano % tam_base:
            raise FitIlegible("tamaño de campo que no es múltiplo de su tipo")
        cantidad = 1 if base == T_STRING else tamano // tam_base
        formato.append(f"{tamano}s" if base == T_STRING else f"{cantidad}{letra}")

        interesa = numero_campo == CAMPO_TIMESTAMP or (
            numero == MENSAJE_RECORD
            and (numero_campo in CAMPOS_RECORD or numero_campo in COMPONENTES_RECORD)
        )
        if interesa and base == T_STRING:
            raise DelegarEnFitparse("texto donde el perfil pide un número")

        if numero == MENSAJE_RECORD and base != T_STRING:
            campo = CAMPOS_RECORD.get(numero_campo)
            componentes = COMPONENTES_RECORD.get(numero_campo)
            if campo is not None or componentes is not None:
                plan.append((indice, cantidad, base, numero_campo, campo, componentes))
            if componentes is not None:
                # fitparse pone a cero los acumuladores cada vez que se define el mensaje.
                for componente in componentes:
                    if componente[6]:
                        acumulados[componente[1]] = 0
        elif numero_campo == CAMPO_TIMESTAMP and base != T_STRING:
            pos_timestamp = (indice, cantidad, base)
        indice += cantidad

    if cabecera & 0x20:
        # Campos de desarrollador (Connect IQ). Ver la nota del módulo.
        raise DelegarEnFitparse("campos de desarrollador")

    locales[cabecera & 0xF] = (numero, struct.Struct("".join(formato)), tuple(plan), pos_timestamp)
    return p


def _valor(valores, indice, cantidad, base):
    """El valor crudo de un campo, con los inválidos a None como en fitparse."""
    invalido = TIPOS_BASE[base][2]
    if base == T_BYTE:
        crudo = tuple(valores[indice : indice + cantidad])
        return None if all(b == 0xFF for b in crudo) else crudo
    if cantidad == 1:
        crudo = valores[indice]
        if invalido is NAN:
            return None if crudo != crudo else crudo
        return None if crudo == invalido else crudo
    if invalido is NAN:
        return tuple(None if v != v else v for v in valores[indice : indice + cantidad])
    return tuple(None if v == invalido else v for v in valores[indice : indice + cantidad])


def _escalar(valor, escala, desplazamiento):
    if valor is None:
        return None
    if isinstance(valor, tuple):
        return tuple(_escalar(v, escala, desplazamiento) for v in valor)
    if escala:
        valor = float(valor) / escala
    if desplazamiento:
        valor = valor - desplazamiento
    return valor


def _fecha(valor):
    if isinstance(valor, tuple):
        # fitparse falla con un timestamp múltiple; que decida él.
        raise DelegarEnFitparse("timestamp con varios valores")
    if valor is not None and valor >= MINIMO_FECHA_ABSOLUTA:
        return EPOCA_FIT + timedelta(seconds=valor)
    return valor


def _acumular(crudo: int, acumulado: int, bits: int) -> int:
    """Reconstruye un valor que el reloj guardó truncado a `bits` bits."""
    maximo = 1 << bits
    mascara = maximo - 1
    valor = crudo + (acumulado & ~mascara)
    if crudo < (acumulado & mascara):
        valor += maximo
    return valor


def _expandir(crudo, componentes, acumulados, registro) -> None:
    """Los componentes de un campo (p. ej. `speed` → `enhanced_speed`), como fitparse."""
    if isinstance(crudo, tuple):
        if any(b is None for b in crudo):
            raise DelegarEnFitparse("componente con un valor inválido dentro")
        entero = 0
        for byte in reversed(crudo):  # fitparse lo lee como bytes en little endian
            entero = (entero << 8) + byte
    else:
        entero = crudo
    for nombre, destino, bits, desplazamiento, escala, desfase, acumula in componentes:
        if entero is None:
            valor = None
        else:
            if isinstance(crudo, tuple) and desplazamiento and desplazamiento >= len(crudo) << 3:
                continue
            valor = (entero >> desplazamiento) & ((1 << bits) - 1)
            if acumula:
                valor = _acumular(valor, acumulados[destino], bits)
                acumulados[destino] = valor
        if nombre in INTERESAN:
            registro[nombre] = _escalar(valor, escala, desfase)
