"""Fotos temporales del registro.

Se guardan SOLO mientras la persona está pendiente, para que el administrador
pueda verlas y decidir. Al aprobar, rechazar o revocar se borran. Lo único que
se conserva de forma permanente es el descriptor facial (una lista de números,
no una foto).

Las fotos viven en fotos/registro/<id de la persona>/<angulo>.jpg. Esa carpeta
cae dentro de /fotos/, que el .gitignore del proyecto ya ignora, así que nunca
se suben a GitHub. Se puede cambiar el lugar con la variable PLUMA_FOTOS_DIR.
"""

import logging
import os
import shutil
from pathlib import Path

import cv2

logger = logging.getLogger("pluma.fotos")

BASE_DIR = Path(__file__).resolve().parents[1]
CARPETA = Path(os.getenv("PLUMA_FOTOS_DIR") or BASE_DIR / "fotos" / "registro")

ANGULOS = ("frente", "izquierda", "derecha")
LADO_MAXIMO = 1280
CALIDAD_JPEG = 85


def _carpeta(persona_id: int) -> Path:
    return CARPETA / str(int(persona_id))


def guardar_foto(persona_id: int, angulo: str, imagen) -> None:
    """Guarda la foto (imagen de OpenCV) como JPG, reemplazando la anterior del mismo ángulo.

    Al volver a codificar la imagen se pierden los metadatos de la foto original
    (ubicación GPS, modelo del celular, etc.) y se reduce su tamaño.
    """
    if angulo not in ANGULOS:
        raise ValueError(f"Ángulo desconocido: {angulo}")

    alto, ancho = imagen.shape[:2]
    lado = max(alto, ancho)
    if lado > LADO_MAXIMO:
        escala = LADO_MAXIMO / lado
        imagen = cv2.resize(
            imagen,
            (int(ancho * escala), int(alto * escala)),
            interpolation=cv2.INTER_AREA,
        )

    listo, codificada = cv2.imencode(
        ".jpg", imagen, [cv2.IMWRITE_JPEG_QUALITY, CALIDAD_JPEG]
    )
    if not listo:
        raise OSError("No se pudo codificar la foto.")

    carpeta = _carpeta(persona_id)
    carpeta.mkdir(parents=True, exist_ok=True)
    destino = carpeta / f"{angulo}.jpg"
    temporal = carpeta / f"{angulo}.tmp"
    temporal.write_bytes(codificada.tobytes())
    os.replace(temporal, destino)   # así nunca queda una foto a medias


def ruta_foto(persona_id: int, angulo: str) -> Path | None:
    """Ruta de la foto, o None si no existe (o ya fue eliminada)."""
    if angulo not in ANGULOS:
        return None
    ruta = _carpeta(persona_id) / f"{angulo}.jpg"
    return ruta if ruta.is_file() else None


def disponibles(persona_id: int) -> dict[str, bool]:
    """Qué fotos de esta persona siguen guardadas."""
    return {angulo: ruta_foto(persona_id, angulo) is not None for angulo in ANGULOS}


def borrar_fotos(persona_id: int) -> bool:
    """Borra todas las fotos de una persona. Devuelve False si no pudo borrarlas."""
    carpeta = _carpeta(persona_id)
    try:
        shutil.rmtree(carpeta)
    except FileNotFoundError:
        return True
    except OSError:
        logger.exception("No se pudieron borrar las fotos de la persona %s", persona_id)
        return False
    return not carpeta.exists()


def limpiar_huerfanas(ids_pendientes: set[int]) -> int:
    """Borra las carpetas de personas que ya no están pendientes.

    Es una red de seguridad: por si el servidor se apagó justo después de una
    decisión, o por si alguna foto quedó suelta. Devuelve cuántas carpetas borró.
    """
    if not CARPETA.is_dir():
        return 0

    borradas = 0
    for hijo in CARPETA.iterdir():
        if not hijo.is_dir():
            continue
        try:
            persona_id = int(hijo.name)
        except ValueError:
            continue
        if persona_id not in ids_pendientes and borrar_fotos(persona_id):
            borradas += 1
    return borradas
