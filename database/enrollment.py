"""Registra una persona y obtiene su descriptor desde una foto."""

import argparse
from pathlib import Path

import cv2
import numpy as np
from mysql.connector import Error as MySQLError

from .repository import register_person


BASE_DIR = Path(__file__).resolve().parents[1]
YUNET_MODEL = BASE_DIR / "modelos" / "face_detection_yunet_2026may.onnx"
SFACE_MODEL = BASE_DIR / "modelos" / "face_recognition_sface_2021dec.onnx"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Registra una persona y su rostro de referencia en MySQL."
    )
    parser.add_argument("nombre", help="Nombre que se guardará en la base")
    parser.add_argument("imagen", help="Ruta de una foto donde aparezca un solo rostro")
    args = parser.parse_args()

    name = args.nombre.strip()
    if not name:
        raise SystemExit("El nombre no puede estar vacío.")

    image_path = Path(args.imagen).expanduser()
    image = cv2.imread(str(image_path))
    if image is None:
        raise SystemExit(f"No pude abrir la imagen: {image_path}")

    detector = cv2.FaceDetectorYN.create(
        str(YUNET_MODEL), "", (320, 320), 0.5, 0.3, 5000
    )
    detector.setInputSize((image.shape[1], image.shape[0]))
    _, faces = detector.detect(image)

    if faces is None or len(faces) == 0:
        raise SystemExit("YuNet no detectó un rostro en la foto.")

    # En fotos de oficina o de grupo pueden aparecer caras en revistas o pantallas.
    # Ordenamos por área y elegimos la cara principal solo si destaca claramente.
    face_areas = faces[:, 2] * faces[:, 3]
    order = np.argsort(face_areas)[::-1]
    faces = faces[order]

    if len(faces) > 1:
        largest_area = face_areas[order[0]]
        second_largest_area = face_areas[order[1]]
        if largest_area < second_largest_area * 2:
            raise SystemExit(
                "Se detectaron varios rostros de tamaño parecido. Recorta la "
                "foto alrededor de la persona que quieres registrar."
            )
        print(
            f"YuNet detectó {len(faces)} rostros; usaré el rostro principal, "
            "que es el más grande."
        )

    recognizer = cv2.FaceRecognizerSF.create(str(SFACE_MODEL), "")
    aligned_face = recognizer.alignCrop(image, faces[0])
    feature = recognizer.feature(aligned_face)
    descriptor = feature.astype("float32", copy=False).tobytes()

    try:
        person_id = register_person(name, descriptor)
    except (ConnectionError, MySQLError) as error:
        raise SystemExit(f"No se pudo registrar a la persona: {error}") from error

    print(f"Persona registrada: {name} (id {person_id}).")
    print(f"Descriptor facial guardado: {feature.shape[1]} valores de SFace.")


if __name__ == "__main__":
    main()
