"""Detección y descriptor facial (YuNet + SFace) para las fotos que sube la web."""

import threading
from pathlib import Path

import cv2
import numpy as np

BASE_DIR = Path(__file__).resolve().parents[1]
YUNET_MODEL = BASE_DIR / "modelos" / "face_detection_yunet_2026may.onnx"
SFACE_MODEL = BASE_DIR / "modelos" / "face_recognition_sface_2021dec.onnx"

LADO_MAXIMO = 1280        # las fotos más grandes se reducen antes de analizarlas
ANCHO_MIN_ROSTRO = 80     # píxeles; menos que esto es un rostro muy lejano
UMBRAL_DETECCION = 0.7    # confianza mínima de YuNet

_candado = threading.Lock()
_detector = None
_reconocedor = None


class RostroInvalido(Exception):
    """La foto no sirve; el mensaje está escrito para mostrárselo a la persona."""


def _cargar_modelos():
    """Carga YuNet y SFace una sola vez (cargarlos en cada petición sería lento)."""
    global _detector, _reconocedor
    if _detector is None:
        _detector = cv2.FaceDetectorYN.create(
            str(YUNET_MODEL), "", (320, 320), UMBRAL_DETECCION, 0.3, 5000
        )
        _reconocedor = cv2.FaceRecognizerSF.create(str(SFACE_MODEL), "")
    return _detector, _reconocedor


def decodificar_imagen(datos: bytes):
    """Convierte los bytes del archivo subido en una imagen de OpenCV."""
    imagen = cv2.imdecode(np.frombuffer(datos, dtype=np.uint8), cv2.IMREAD_COLOR)
    if imagen is None:
        raise RostroInvalido("El archivo no es una imagen válida.")
    return imagen


def extraer_descriptor(imagen) -> bytes:
    """Devuelve el descriptor SFace (128 float32 = 512 bytes) del rostro principal."""
    alto, ancho = imagen.shape[:2]
    lado = max(alto, ancho)
    if lado > LADO_MAXIMO:
        escala = LADO_MAXIMO / lado
        imagen = cv2.resize(
            imagen,
            (int(ancho * escala), int(alto * escala)),
            interpolation=cv2.INTER_AREA,
        )
        alto, ancho = imagen.shape[:2]

    # Los modelos se comparten entre peticiones, así que solo uno trabaja a la vez.
    with _candado:
        detector, reconocedor = _cargar_modelos()
        detector.setInputSize((ancho, alto))
        _, rostros = detector.detect(imagen)

        if rostros is None or len(rostros) == 0:
            raise RostroInvalido(
                "No detectamos ningún rostro. Busca buena luz y mira a la cámara."
            )

        # Misma regla que enrollment.py: el rostro principal debe destacar.
        areas = rostros[:, 2] * rostros[:, 3]
        orden = np.argsort(areas)[::-1]
        rostros = rostros[orden]
        if len(rostros) > 1 and areas[orden[0]] < areas[orden[1]] * 2:
            raise RostroInvalido(
                "Detectamos más de un rostro. La foto debe salir solo tú."
            )

        rostro = rostros[0]
        if rostro[2] < ANCHO_MIN_ROSTRO:
            raise RostroInvalido("Tu rostro se ve muy pequeño. Acércate a la cámara.")

        alineado = reconocedor.alignCrop(imagen, rostro)
        descriptor = reconocedor.feature(alineado)

    return descriptor.astype("float32", copy=False).tobytes()


UMBRAL_MISMA_PERSONA = 0.25  # entre las fotos de un mismo registro (tolera giros de cabeza)
UMBRAL_DUPLICADO = 0.363     # el mismo umbral que usa la cámara para decir "es la misma persona"


def similitud(descriptor_a: bytes, descriptor_b: bytes) -> float:
    """Similitud coseno entre dos descriptores SFace (1 = idéntico, 0 = nada que ver)."""
    a = np.frombuffer(descriptor_a, dtype=np.float32)
    b = np.frombuffer(descriptor_b, dtype=np.float32)
    if a.shape != b.shape:
        return 0.0
    norma = float(np.linalg.norm(a) * np.linalg.norm(b))
    if norma == 0.0:
        return 0.0
    return float(np.dot(a, b) / norma)