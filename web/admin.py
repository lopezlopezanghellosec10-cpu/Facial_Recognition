"""Endpoints del panel de administración, protegidos con una clave."""

import hmac
import os
from enum import StrEnum

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException
from pydantic import BaseModel, field_validator

from .limites import Limitador
from .notificaciones import notificar
from .repositorio import (
    aprobar_persona,
    contar_por_estado,
    listar_por_estado,
    obtener_descriptores,
    obtener_descriptores_ajenos,
    obtener_persona,
    rechazar_persona,
    revocar_persona,
)
from .rostros import UMBRAL_DUPLICADO, similitud

limite_admin = Limitador(300, 600)  # 300 peticiones cada 10 minutos por IP


def exigir_admin(x_admin_key: str = Header(...)) -> None:
    """Deja pasar solo las peticiones que traen la clave de administrador."""
    clave = os.getenv("ADMIN_KEY")
    if not clave:
        raise HTTPException(
            status_code=503,
            detail="El panel no está configurado: falta la variable ADMIN_KEY.",
        )
    if not hmac.compare_digest(x_admin_key.encode("utf-8"), clave.encode("utf-8")):
        raise HTTPException(status_code=403, detail="Clave de administrador incorrecta.")


router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(limite_admin), Depends(exigir_admin)],
)


class Estado(StrEnum):
    pendiente = "pendiente"
    aprobado = "aprobado"
    rechazado = "rechazado"


class MotivoEntrada(BaseModel):
    motivo: str

    @field_validator("motivo")
    @classmethod
    def validar_motivo(cls, valor: str) -> str:
        valor = " ".join(valor.split())
        if len(valor) < 5:
            raise ValueError("Escribe el motivo (mínimo 5 caracteres).")
        if len(valor) > 500:
            raise ValueError("El motivo es demasiado largo (máximo 500 caracteres).")
        return valor


def _cargar_persona(persona_id: int) -> dict:
    persona = obtener_persona(persona_id)
    if persona is None:
        raise HTTPException(status_code=404, detail="No existe esa persona.")
    return persona


def _buscar_parecidos(persona_id: int) -> list[dict]:
    """Otras personas cuyo rostro se parece tanto que la cámara las confundiría."""
    propios = obtener_descriptores(persona_id)
    if not propios:
        return []

    mejores: dict[int, dict] = {}
    for ajeno in obtener_descriptores_ajenos(persona_id):
        valor = max(similitud(propio, ajeno["descriptor"]) for propio in propios)
        if valor < UMBRAL_DUPLICADO:
            continue
        actual = mejores.get(ajeno["persona_id"])
        if actual is None or valor > actual["similitud"]:
            mejores[ajeno["persona_id"]] = {
                "persona_id": ajeno["persona_id"],
                "nombre": ajeno["nombre"],
                "estado": ajeno["estado"],
                "similitud": round(valor, 3),
            }
    return sorted(mejores.values(), key=lambda p: p["similitud"], reverse=True)


@router.get("/resumen")
def resumen():
    return contar_por_estado()


@router.get("/pendientes")
def pendientes():
    return listar_por_estado("pendiente")


@router.get("/personas")
def listar(estado: Estado = Estado.pendiente):
    return listar_por_estado(estado.value)


@router.get("/personas/{persona_id}")
def detalle(persona_id: int):
    persona = _cargar_persona(persona_id)
    persona["parecidos"] = _buscar_parecidos(persona_id)
    return persona


@router.post("/personas/{persona_id}/aprobar")
def aprobar(persona_id: int, segundo_plano: BackgroundTasks):
    persona = _cargar_persona(persona_id)
    if persona["estado"] != "pendiente":
        raise HTTPException(
            status_code=409, detail=f"Esta persona ya está {persona['estado']}."
        )
    if persona["faltan"]:
        raise HTTPException(
            status_code=409,
            detail="No se puede aprobar, faltan fotos: "
            + ", ".join(persona["faltan"])
            + ". Puedes rechazar el registro con un mensaje.",
        )
    if not aprobar_persona(persona_id):
        raise HTTPException(status_code=409, detail="Esta persona ya fue revisada.")

    segundo_plano.add_task(
        notificar,
        persona["correo"],
        "Tu registro fue aprobado",
        f"Hola {persona['nombre']}, tu registro fue aprobado. "
        "Ya puedes usar el acceso automático de la pluma.",
    )
    return {"persona_id": persona_id, "estado": "aprobado"}


@router.post("/personas/{persona_id}/rechazar")
def rechazar(persona_id: int, datos: MotivoEntrada, segundo_plano: BackgroundTasks):
    persona = _cargar_persona(persona_id)
    if persona["estado"] != "pendiente":
        raise HTTPException(
            status_code=409, detail=f"Esta persona ya está {persona['estado']}."
        )
    if not rechazar_persona(persona_id, datos.motivo):
        raise HTTPException(status_code=409, detail="Esta persona ya fue revisada.")

    segundo_plano.add_task(
        notificar,
        persona["correo"],
        "Tu registro no pudo ser aprobado",
        f"Hola {persona['nombre']}, revisamos tu registro y no pudo ser aprobado.\n\n"
        f"Motivo: {datos.motivo}\n\n"
        "Puedes volver a registrarte con el mismo correo corrigiendo lo indicado.",
    )
    return {"persona_id": persona_id, "estado": "rechazado", "motivo": datos.motivo}


@router.post("/personas/{persona_id}/revocar")
def revocar(persona_id: int, datos: MotivoEntrada, segundo_plano: BackgroundTasks):
    persona = _cargar_persona(persona_id)
    if persona["estado"] != "aprobado":
        raise HTTPException(
            status_code=409,
            detail=f"Solo se puede desactivar a alguien aprobado (está {persona['estado']}).",
        )
    if not revocar_persona(persona_id, datos.motivo):
        raise HTTPException(status_code=409, detail="Esta persona ya fue revisada.")

    segundo_plano.add_task(
        notificar,
        persona["correo"],
        "Tu acceso fue desactivado",
        f"Hola {persona['nombre']}, tu acceso automático a la pluma fue desactivado.\n\n"
        f"Motivo: {datos.motivo}",
    )
    return {"persona_id": persona_id, "estado": "rechazado", "motivo": datos.motivo}