"""Reconoce en cámara a personas registradas en MySQL y muestra la guía facial."""

import argparse
from pathlib import Path

import cv2
import numpy as np
from mysql.connector import Error as MySQLError

from database.repository import get_registered_faces


BASE_DIR = Path(__file__).resolve().parent
YUNET_MODEL = BASE_DIR / "modelos" / "face_detection_yunet_2026may.onnx"
SFACE_MODEL = BASE_DIR / "modelos" / "face_recognition_sface_2021dec.onnx"

GUIDE_WIDTH_RATIO = 0.38
GUIDE_HEIGHT_RATIO = 0.62
MIN_FACE_WIDTH_RATIO = 0.38
MAX_FACE_WIDTH_RATIO = 0.78
MIN_FACE_HEIGHT_RATIO = 0.35
MAX_FACE_HEIGHT_RATIO = 0.76
CENTER_TOLERANCE_X = 0.12
CENTER_TOLERANCE_Y = 0.12
COSINE_THRESHOLD = 0.363


def draw_label(frame, text, y, color, scale=0.7):
    """Dibuja texto legible con un contorno oscuro."""
    font = cv2.FONT_HERSHEY_SIMPLEX
    cv2.putText(frame, text, (24, y), font, scale, (20, 20, 20), 4, cv2.LINE_AA)
    cv2.putText(frame, text, (24, y), font, scale, color, 2, cv2.LINE_AA)


def load_face_features():
    """Carga de MySQL cada descriptor activo y lo convierte a un arreglo SFace."""
    try:
        rows = get_registered_faces()
    except (ConnectionError, MySQLError) as error:
        raise SystemExit(f"No se pudieron cargar los rostros de MySQL: {error}") from error

    if not rows:
        raise SystemExit(
            "No hay rostros registrados. Registra una persona primero con "
            "python -m database.enrollment."
        )

    features = []
    for person_id, name, descriptor_blob in rows:
        descriptor = np.frombuffer(descriptor_blob, dtype=np.float32)
        if descriptor.size == 0:
            raise SystemExit(f"El descriptor guardado para {name} está vacío.")
        features.append((person_id, name, descriptor.reshape(1, -1)))

    return features


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Reconoce en vivo a las personas registradas en la base de datos."
    )
    parser.add_argument(
        "--camara",
        type=int,
        default=0,
        help="Índice de la cámara (0 normalmente es la integrada; prueba 1 para una webcam USB)",
    )
    args = parser.parse_args()

    database_features = load_face_features()
    person_count = len({person_id for person_id, _, _ in database_features})
    print(
        f"Cargadas {person_count} persona(s) y "
        f"{len(database_features)} descriptor(es) facial(es) desde MySQL."
    )

    detector = cv2.FaceDetectorYN.create(
        str(YUNET_MODEL), "", (320, 320), 0.5, 0.3, 5000
    )
    recognizer = cv2.FaceRecognizerSF.create(str(SFACE_MODEL), "")

    camera = cv2.VideoCapture(args.camara)
    if not camera.isOpened():
        raise SystemExit("No se pudo abrir la cámara seleccionada.")

    try:
        while True:
            ok, frame = camera.read()
            if not ok:
                print("No se pudo leer el fotograma.")
                break

            height, width = frame.shape[:2]
            center_x, center_y = width // 2, height // 2
            guide_w = int(width * GUIDE_WIDTH_RATIO)
            guide_h = int(height * GUIDE_HEIGHT_RATIO)
            axes = (guide_w // 2, guide_h // 2)

            detector.setInputSize((width, height))
            _, faces = detector.detect(frame)

            guide_color = (0, 180, 255)
            status = "Coloca tu rostro dentro de la guia"
            detail = "Alinea el rostro y ajusta la distancia"

            if faces is None or len(faces) == 0:
                status = "No se detecta un rostro"
                detail = "Mira hacia la camara"
            elif len(faces) > 1:
                guide_color = (0, 0, 255)
                status = "Se detecto mas de un rostro"
                detail = "Deja solo una persona frente a la camara"
            else:
                face = faces[0]
                x, y, face_w, face_h = face[:4]
                face_center_x = x + face_w / 2
                face_center_y = y + face_h / 2
                width_ratio = face_w / guide_w
                height_ratio = face_h / guide_h
                centered = (
                    abs(face_center_x - center_x) <= guide_w * CENTER_TOLERANCE_X
                    and abs(face_center_y - center_y) <= guide_h * CENTER_TOLERANCE_Y
                )
                correct_size = (
                    MIN_FACE_WIDTH_RATIO <= width_ratio <= MAX_FACE_WIDTH_RATIO
                    and MIN_FACE_HEIGHT_RATIO <= height_ratio <= MAX_FACE_HEIGHT_RATIO
                )
                face_ready = centered and correct_size

                if face_ready:
                    guide_color = (60, 200, 60)
                    status = "Rostro bien colocado"
                    detail = "Comparando con personas registradas..."
                else:
                    if not centered:
                        dx = face_center_x - center_x
                        dy = face_center_y - center_y
                        if abs(dx) > guide_w * CENTER_TOLERANCE_X:
                            detail = "Mueve el rostro hacia el centro"
                        elif dy < 0:
                            detail = "Baja un poco el rostro"
                        else:
                            detail = "Sube un poco el rostro"
                    elif width_ratio < MIN_FACE_WIDTH_RATIO or height_ratio < MIN_FACE_HEIGHT_RATIO:
                        detail = "Acercate un poco a la camara"
                    else:
                        detail = "Alejate un poco de la camara"

                x, y, face_w, face_h = map(int, (x, y, face_w, face_h))

                if face_ready:
                    live_aligned = recognizer.alignCrop(frame, face)
                    live_feature = recognizer.feature(live_aligned)
                    best_person = None
                    best_similarity = -1.0

                    for person_id, name, stored_feature in database_features:
                        similarity = recognizer.match(
                            stored_feature,
                            live_feature,
                            cv2.FaceRecognizerSF_FR_COSINE,
                        )
                        if similarity > best_similarity:
                            best_person = (person_id, name)
                            best_similarity = similarity

                    if best_person is not None and best_similarity >= COSINE_THRESHOLD:
                        guide_color = (60, 220, 60)
                        status = f"Reconocido: {best_person[1]}"
                        detail = f"Coincidencia | Coseno: {best_similarity:.3f}"
                    else:
                        guide_color = (80, 80, 255)
                        status = "Persona no registrada"
                        detail = (
                            f"Mejor coseno: {best_similarity:.3f} "
                            f"| Umbral: {COSINE_THRESHOLD:.3f}"
                        )

                cv2.rectangle(frame, (x, y), (x + face_w, y + face_h), guide_color, 2)

            cv2.ellipse(frame, (center_x, center_y), axes, 0, 0, 360, guide_color, 3)
            cv2.ellipse(frame, (center_x, center_y), axes, 0, 205, 235, guide_color, 6)
            draw_label(frame, status, 36, guide_color)
            draw_label(frame, detail, 68, (255, 255, 255), 0.58)

            draw_label(frame, "Presiona Q para salir", height - 24, (220, 220, 220), 0.55)

            cv2.imshow("Camara - reconocimiento facial", frame)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    finally:
        camera.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
