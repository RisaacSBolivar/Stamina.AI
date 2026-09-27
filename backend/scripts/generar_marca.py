"""
Genera los assets de marca del frontend a partir de `frontend/marca/logo-original.jpg`.

El original es un lockup horizontal de 2816x1536 que ya incluye la palabra
«STAMINA.AI» sobre un fondo crema opaco (249, 246, 241). Para la interfaz no
sirve tal cual: el header ya escribe el nombre, y un rectangulo crema sobre el
azul marino se ve como un parche. Lo que hace falta es solo el corredor, con
fondo transparente.

De ahi los tres pasos: recortar el bloque del corredor (el texto empieza en
x=1250), convertir el crema en transparencia por distancia al color de fondo, y
descartar la sombra gris del pie, que al perder el fondo quedaria como una
mancha clara flotando.

Se ejecuta una sola vez y sus salidas se versionan; no corre en cada build.

    make marca
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

RAIZ = Path(__file__).resolve().parents[2]
ORIGEN = RAIZ / "frontend" / "marca" / "logo-original.jpg"
DESTINO = RAIZ / "frontend" / "public"

# El texto del lockup empieza en x=1250: todo lo que se mire queda a su izquierda.
CORTE_TEXTO = 1240

# Recortar por columna no basta: la «S» de STAMINA asoma antes de ese corte. El
# corredor y sus llamas son manchas que empiezan a la izquierda de x=1200 (la
# mayor arranca en x=412); cualquier mancha que nazca a la derecha es tipografia.
INICIO_TIPOGRAFIA = 1200

# Fondo crema del original, medido en las cuatro esquinas.
FONDO = np.array([249, 246, 241])

# Transparencia por distancia al fondo. Por debajo de OPACO_DESDE es fondo puro;
# entre los dos umbrales se degrada, que es lo que da el borde suave.
TRANSPARENTE_HASTA = 12
OPACO_DESDE = 45

# La sombra del pie es gris claro y sin color. La tinta del corredor es azul
# marino saturado o naranja, asi que separa bien: gris + claro = sombra.
SOMBRA_SATURACION_MAX = 28
SOMBRA_LUZ_MIN = 150

ALTO_LOGO = 128  # el header lo pinta a 32 px; sobra para pantallas 3x
TAMANOS_ICO = [(16, 16), (32, 32), (48, 48)]
ALTO_APPLE = 180


def _recortar_corredor(img: Image.Image) -> Image.Image:
    """Deja solo el corredor, ya con canal alfa y sin sombra."""
    rgb = np.asarray(img.convert("RGB")).astype(np.int16)[:, :CORTE_TEXTO]

    distancia = np.abs(rgb - FONDO).max(axis=2)
    alfa = (distancia - TRANSPARENTE_HASTA) / (OPACO_DESDE - TRANSPARENTE_HASTA)
    alfa = np.clip(alfa, 0.0, 1.0)

    saturacion = rgb.max(axis=2) - rgb.min(axis=2)
    luz = rgb.mean(axis=2)
    alfa[(saturacion < SOMBRA_SATURACION_MAX) & (luz > SOMBRA_LUZ_MIN)] = 0.0

    alfa = _sin_tipografia(alfa)

    salida = np.dstack([rgb.astype(np.uint8), (alfa * 255).astype(np.uint8)])
    recorte = Image.fromarray(salida, mode="RGBA")

    caja = recorte.getbbox()  # recorta al contenido real, sin margenes muertos
    if caja is None:
        raise SystemExit("El recorte salio vacio: revisa los umbrales de transparencia.")
    return recorte.crop(caja)


def _sin_tipografia(alfa: np.ndarray) -> np.ndarray:
    """Borra las manchas que nacen a la derecha del corredor: son letras."""
    etiquetas, cuantas = ndimage.label(alfa > 0.15)
    for etiqueta, caja in enumerate(ndimage.find_objects(etiquetas), start=1):
        if caja is not None and caja[1].start > INICIO_TIPOGRAFIA:
            alfa[etiquetas == etiqueta] = 0.0
    return alfa


def _a_alto(img: Image.Image, alto: int) -> Image.Image:
    ancho = max(1, round(img.width * alto / img.height))
    return img.resize((ancho, alto), Image.LANCZOS)


def _cuadrado(img: Image.Image, lado: int, fondo: tuple[int, int, int, int]) -> Image.Image:
    """Centra el corredor en un lienzo cuadrado, con un margen del 8 %."""
    util = round(lado * 0.84)
    escala = min(util / img.width, util / img.height)
    pieza = img.resize(
        (max(1, round(img.width * escala)), max(1, round(img.height * escala))), Image.LANCZOS
    )

    lienzo = Image.new("RGBA", (lado, lado), fondo)
    lienzo.paste(pieza, ((lado - pieza.width) // 2, (lado - pieza.height) // 2), pieza)
    return lienzo


def main() -> int:
    if not ORIGEN.exists():
        print(f"No encuentro {ORIGEN}", file=sys.stderr)
        return 1

    DESTINO.mkdir(parents=True, exist_ok=True)
    corredor = _recortar_corredor(Image.open(ORIGEN))
    print(f"corredor recortado: {corredor.width}x{corredor.height}")

    logo = _a_alto(corredor, ALTO_LOGO)
    logo.save(DESTINO / "logo-stamina.png", optimize=True)

    _cuadrado(corredor, 32, (0, 0, 0, 0)).save(DESTINO / "favicon-32x32.png", optimize=True)
    # Pillow reescala solo a cada tamano del .ico desde este lienzo de 256.
    _cuadrado(corredor, 256, (0, 0, 0, 0)).save(DESTINO / "favicon.ico", sizes=TAMANOS_ICO)

    # Apple compone sobre negro si hay transparencia, asi que este va opaco.
    _cuadrado(corredor, ALTO_APPLE, (255, 255, 255, 255)).convert("RGB").save(
        DESTINO / "apple-touch-icon.png", optimize=True
    )

    for nombre in ("logo-stamina.png", "favicon.ico", "favicon-32x32.png", "apple-touch-icon.png"):
        ruta = DESTINO / nombre
        print(f"  {nombre}: {ruta.stat().st_size / 1024:.1f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
