"""Prueba local de los modelos YuNet y SFace con una imagen."""

import argparse
from pathlib import Path

import cv2


BASE_DIR = Path(__file__).resolve().parent
YUNET_MODEL = BASE_DIR / "modelos" / "face_detection_yunet_2026may.onnx"
SFACE_MODEL = BASE_DIR / "modelos" / "face_recognition_sface_2021dec.onnx"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Comprueba YuNet (detección) y SFace (representación facial)."
    )
    parser.add_argument("imagen", help="Ruta de una imagen que contenga un rostro")
    args = parser.parse_args()

    image_path = Path(args.imagen).expanduser()
    image = cv2.imread(str(image_path))
    if image is None:
        raise SystemExit(f"No pude abrir la imagen: {image_path}")

    detector = cv2.FaceDetectorYN.create(
        str(YUNET_MODEL), "", (320, 320), 0.8, 0.3, 5000
    )
    detector.setInputSize((image.shape[1], image.shape[0]))
    recognizer = cv2.FaceRecognizerSF.create(str(SFACE_MODEL), "")

    _, faces = detector.detect(image)
    count = 0 if faces is None else len(faces)
    print(f"YuNet detectó {count} rostro(s).")

    if count == 0:
        print("Prueba con una imagen clara, de frente y con el rostro visible.")
        return

    aligned_face = recognizer.alignCrop(image, faces[0])
    features = recognizer.feature(aligned_face)
    print(f"SFace generó una representación de {features.shape[1]} valores.")
    print("Los dos modelos cargaron y procesaron la imagen correctamente.")


if __name__ == "__main__":
    main()
