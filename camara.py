"""Prueba de reconocimiento facial en cámara con guía de posicionamiento."""

import argparse
from pathlib import Path

import cv2


BASE_DIR = Path(__file__).resolve().parent
YUNET_MODEL = BASE_DIR / "modelos" / "face_detection_yunet_2026may.onnx"
SFACE_MODEL = BASE_DIR / "modelos" / "face_recognition_sface_2021dec.onnx"

# El óvalo representa el área donde debe colocarse el rostro. YuNet devuelve
# el rectángulo facial; se compara su centro y tamaño con esta guía.
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
    """Dibuja texto legible con contorno oscuro."""
    font = cv2.FONT_HERSHEY_SIMPLEX
    cv2.putText(frame, text, (24, y), font, scale, (20, 20, 20), 4, cv2.LINE_AA)
    cv2.putText(frame, text, (24, y), font, scale, color, 2, cv2.LINE_AA)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compara el rostro de referencia con la cámara y muestra una guía."
    )
    parser.add_argument("referencia", help="Ruta a la foto de referencia")
    parser.add_argument(
        "--camara",
        type=int,
        default=0,
        help="Índice de la cámara (0 normalmente es la integrada; prueba 1 para una webcam USB)",
    )
    args = parser.parse_args()

    detector = cv2.FaceDetectorYN.create(
        str(YUNET_MODEL), "", (320, 320), 0.5, 0.3, 5000
    )
    recognizer = cv2.FaceRecognizerSF.create(str(SFACE_MODEL), "")

    reference_path = Path(args.referencia).expanduser()
    reference_image = cv2.imread(str(reference_path))
    if reference_image is None:
        raise SystemExit(f"No pude abrir la imagen de referencia: {reference_path}")

    detector.setInputSize((reference_image.shape[1], reference_image.shape[0]))
    _, reference_faces = detector.detect(reference_image)
    if reference_faces is None or len(reference_faces) == 0:
        raise SystemExit("YuNet no detectó un rostro en la foto de referencia.")

    reference_aligned = recognizer.alignCrop(reference_image, reference_faces[0])
    reference_feature = recognizer.feature(reference_aligned)
    print(f"Referencia lista: {reference_feature.shape[1]} valores.")

    camera = cv2.VideoCapture(args.camara)
    if not camera.isOpened():
        raise SystemExit("No se pudo abrir la cámara.")

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

            guide_color = (0, 180, 255)  # ámbar: rostro pendiente de ajustar
            status = "Coloca tu rostro dentro de la guia"
            detail = "Alinea el rostro y ajusta la distancia"
            face_ready = False

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
                    detail = "Comparando con la referencia..."
                else:
                    guide_color = (0, 180, 255)
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
                cv2.rectangle(frame, (x, y), (x + face_w, y + face_h), guide_color, 2)

                # Solo muestra el puntaje cuando el rostro está bien colocado.
                if face_ready:
                    aligned = recognizer.alignCrop(frame, face)
                    feature = recognizer.feature(aligned)
                    similarity = recognizer.match(
                        reference_feature,
                        feature,
                        cv2.FaceRecognizerSF_FR_COSINE,
                    )
                    match_text = (
                        "Coincidencia"
                        if similarity >= COSINE_THRESHOLD
                        else "Sin coincidencia"
                    )
                    draw_label(
                        frame,
                        f"{match_text} | Coseno: {similarity:.3f}",
                        height - 24,
                        (60, 220, 60) if similarity >= COSINE_THRESHOLD else (80, 80, 255),
                        0.65,
                    )

            cv2.ellipse(frame, (center_x, center_y), axes, 0, 0, 360, guide_color, 3)
            # Marcas cortas en el óvalo que hacen más visible el área objetivo.
            cv2.ellipse(frame, (center_x, center_y), axes, 0, 205, 235, guide_color, 6)
            draw_label(frame, status, 36, guide_color)
            draw_label(frame, detail, 68, (255, 255, 255), 0.58)
            draw_label(frame, "Presiona Q para salir", height - 24, (220, 220, 220), 0.55)

            cv2.imshow("Camara - guia facial", frame)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    finally:
        camera.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
