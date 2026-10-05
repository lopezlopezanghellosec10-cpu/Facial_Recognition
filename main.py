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
    parser.add_argument("imagen1", help="Ruta de la primera imagen")
    parser.add_argument("imagen2", help="Ruta de la segunda imagen")
    args = parser.parse_args()

    image_path1 = Path(args.imagen1).expanduser()
    image_path2 = Path(args.imagen2).expanduser()

    image1 = cv2.imread(str(image_path1))
    image2 = cv2.imread(str(image_path2))

    if image1 is None:
        raise SystemExit(f"No pude abrir la primera imagen: {image_path1}")
    if image2 is None:
        raise SystemExit(f"No pude abrir la segunda imagen: {image_path2}")
    detector = cv2.FaceDetectorYN.create(
        str(YUNET_MODEL), "", (320, 320), 0.7, 0.3, 5000
    )
    detector.setInputSize((image1.shape[1], image1.shape[0]))
    recognizer = cv2.FaceRecognizerSF.create(str(SFACE_MODEL), "")

    _, faces1 = detector.detect(image1)
    detector.setInputSize((image2.shape[1], image2.shape[0]))
    _, faces2 = detector.detect(image2)
    count1 = 0 if faces1 is None else len(faces1)
    count2 = 0 if faces2 is None else len(faces2)
    print(f"YuNet detectó {count1} rostro(s) en la primera imagen.")
    print(f"YuNet detectó {count2} rostro(s) en la segunda imagen.")

    if count1 == 0 or count2 == 0:
        print("Prueba con una imagen clara, de frente y con el rostro visible.")
        return

    aligned_face1 = recognizer.alignCrop(image1, faces1[0])
    aligned_face2 = recognizer.alignCrop(image2, faces2[0])

    feature1 = recognizer.feature(aligned_face1)
    feature2 = recognizer.feature(aligned_face2)

    print(f"Representacion 1: {feature1.shape[1]} valores")
    print(f"Representacion 2: {feature2.shape[1]} valores")

    similarity = recognizer.match(
        feature1,
        feature2,
        cv2.FaceRecognizerSF_FR_COSINE,
    )
    print(f"Similitud coseno: {similarity:.3f}")
    COSINE_THRESHOLD = 0.363

    if similarity >= COSINE_THRESHOLD:

     print("Posible coincidencia")
    
    else:
     print("Sin coincidencia")


if __name__ == "__main__":
    main()




