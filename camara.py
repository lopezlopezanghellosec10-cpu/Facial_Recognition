from pathlib import Path

import cv2
import argparse 

BASE_DIR = Path(__file__).resolve().parent
YUNET_MODEL = BASE_DIR / "modelos" / "face_detection_yunet_2026may.onnx"
SFACE_MODEL = BASE_DIR / "modelos" / "face_recognition_sface_2021dec.onnx"

detector = cv2.FaceDetectorYN.create(
    str(YUNET_MODEL), "", (320, 320), 0.5, 0.3, 5000
)
recognizer = cv2.FaceRecognizerSF.create(str(SFACE_MODEL), "")

parser = argparse.ArgumentParser()
parser.add_argument("referencia", help="Ruta a la foto de referencia")
args = parser.parse_args()

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

camera = cv2.VideoCapture(0)
if not camera.isOpened():
    raise SystemExit("No se pudo abrir la cámara.")

while True:
    ok, frame = camera.read()
    if not ok:
        print("No se pudo leer el fotograma")
        break

    alto, ancho = frame.shape[:2]
    detector.setInputSize((ancho, alto))
    _, rostros = detector.detect(frame)

    if rostros is not None:
        for rostro in rostros:
            x, y, w, h = rostro[:4].astype(int)
            live_aligned = recognizer.alignCrop(frame, rostro)
            live_feature = recognizer.feature(live_aligned)

            similarity = recognizer.match(
              reference_feature,
              live_feature,
              cv2.FaceRecognizerSF_FR_COSINE
            )

            cv2.putText(
              frame,
              f"Coseno: {similarity:.3f}",
              (x, max(y - 10, 20)),
              cv2.FONT_HERSHEY_SIMPLEX,
              0.7,
              (255, 255, 255),
              2
            )
            cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)

    cv2.imshow("Camara", frame)

    if cv2.waitKey(1) & 0xFF == ord("q"):
        break

camera.release()
cv2.destroyAllWindows()
