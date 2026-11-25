import logging
import os
from contextlib import asynccontextmanager
from enum import StrEnum
from pathlib import Path

from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    Request,
    UploadFile,
)
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import admin, fotos
from .esquemas import RegistroEntrada
from .limites import Limitador
from .repositorio import (
    CorreoDuplicado,
    crear_persona_pendiente,
    guardar_rostro,
    listar_por_estado,
    obtener_descriptores,
    obtener_estado_registro,
    obtener_hash_token,
)
from .rostros import (
    UMBRAL_MISMA_PERSONA,
    RostroInvalido,
    decodificar_imagen,
    extraer_descriptor,
    similitud,
)
from .seguridad import generar_token, hash_token, token_coincide

logger = logging.getLogger("pluma.web")

TAMANO_MAXIMO = 5 * 1024 * 1024  # 5 MB por foto
CARPETA_PAGINA = Path(__file__).resolve().parent / "static"
CARPETA_PAGINA.mkdir(exist_ok=True)

# Con PLUMA_PUBLICO=1 (cuando la página se publica en internet) se apaga la
# documentación automática /docs: es para desarrolladores y no hace falta afuera.
PUBLICO = os.getenv("PLUMA_PUBLICO") == "1"

# Límites por IP: (peticiones, segundos)
limite_registro = Limitador(20, 600)
limite_fotos = Limitador(60, 600)
limite_estado = Limitador(120, 600)


@asynccontextmanager
async def ciclo_de_vida(app: FastAPI):
    """Al arrancar, borra fotos que hayan quedado de personas que ya no están pendientes."""
    try:
        pendientes = {persona["id"] for persona in listar_por_estado("pendiente")}
        borradas = fotos.limpiar_huerfanas(pendientes)
        if borradas:
            logger.info("Se borraron las fotos sueltas de %s persona(s).", borradas)
    except Exception:
        # Si MySQL está apagado el servidor arranca igual; se limpia en el próximo arranque.
        logger.warning("No se pudo limpiar las fotos sueltas al arrancar.", exc_info=True)
    yield


app = FastAPI(
    title="Registro Pluma",
    lifespan=ciclo_de_vida,
    docs_url=None if PUBLICO else "/docs",
    redoc_url=None if PUBLICO else "/redoc",
    openapi_url=None if PUBLICO else "/openapi.json",
)
app.include_router(admin.router)


class Angulo(StrEnum):
    frente = "frente"
    izquierda = "izquierda"
    derecha = "derecha"


@app.exception_handler(ConnectionError)
async def base_de_datos_caida(request: Request, error: ConnectionError):
    """Cualquier ConnectionError (MySQL apagado) se responde como 503."""
    return JSONResponse(
        status_code=503,
        content={"detail": "No se pudo conectar a la base de datos."},
    )


@app.get("/salud")
def salud():
    return {"ok": True}


@app.get("/panel", include_in_schema=False)
def panel():
    """Atajo fácil de escribir para el panel del administrador."""
    return RedirectResponse("/admin.html")


@app.post("/registro", status_code=201, dependencies=[Depends(limite_registro)])
def registrar(datos: RegistroEntrada):
    token = generar_token()
    try:
        persona_id = crear_persona_pendiente(
            datos.nombre, datos.telefono, datos.correo, hash_token(token)
        )
    except CorreoDuplicado:
        raise HTTPException(status_code=409, detail="Ese correo ya está registrado.")
    return {"persona_id": persona_id, "estado": "pendiente", "token": token}


@app.post(
    "/registro/{persona_id}/rostro",
    status_code=201,
    dependencies=[Depends(limite_fotos)],
)
def subir_rostro(
    persona_id: int,
    angulo: Angulo = Form(...),
    foto: UploadFile = File(...),
    x_token: str = Header(...),
):
    if not token_coincide(x_token, obtener_hash_token(persona_id)):
        raise HTTPException(
            status_code=403, detail="Token inválido o registro ya cerrado."
        )

    datos = foto.file.read(TAMANO_MAXIMO + 1)
    if len(datos) > TAMANO_MAXIMO:
        raise HTTPException(status_code=413, detail="La foto pesa más de 5 MB.")

    try:
        imagen = decodificar_imagen(datos)
        descriptor = extraer_descriptor(imagen)
    except RostroInvalido as error:
        raise HTTPException(status_code=422, detail=str(error))

    # Todas las fotos de un registro deben ser de la misma persona.
    previos = obtener_descriptores(persona_id, excepto=angulo.value)
    coincidencia = None
    if previos:
        coincidencia = max(similitud(descriptor, previo) for previo in previos)
        if coincidencia < UMBRAL_MISMA_PERSONA:
            raise HTTPException(
                status_code=422,
                detail="Esta foto no parece ser de la misma persona que las anteriores.",
            )

    # La foto se guarda solo para que el administrador la revise; se borra al decidir.
    try:
        fotos.guardar_foto(persona_id, angulo.value, imagen)
    except OSError:
        logger.exception("No se pudo guardar la foto temporal de la persona %s", persona_id)
        raise HTTPException(
            status_code=500, detail="No pudimos guardar tu foto. Intenta de nuevo."
        )

    # Si alguien decidió justo mientras subías la foto, no dejamos fotos sueltas.
    if obtener_hash_token(persona_id) is None:
        fotos.borrar_fotos(persona_id)
        raise HTTPException(
            status_code=403, detail="Token inválido o registro ya cerrado."
        )

    guardados = guardar_rostro(persona_id, angulo.value, descriptor)
    faltan = [a.value for a in Angulo if a.value not in guardados]
    return {
        "guardado": angulo.value,
        "faltan": faltan,
        "completo": not faltan,
        "coincidencia": None if coincidencia is None else round(coincidencia, 3),
    }


@app.get("/registro/{persona_id}/estado", dependencies=[Depends(limite_estado)])
def estado_registro(persona_id: int, x_token: str = Header(...)):
    info = obtener_estado_registro(persona_id)
    if info is None or not token_coincide(x_token, info["token_hash"]):
        raise HTTPException(status_code=403, detail="Token inválido.")
    return {
        "estado": info["estado"],
        "motivo": info["motivo_rechazo"],
        "faltan": info["faltan"],
    }


# Debe ir al final: sirve la carpeta web/static en "/" sin tapar las rutas de arriba.
app.mount("/", StaticFiles(directory=CARPETA_PAGINA, html=True), name="pagina")
