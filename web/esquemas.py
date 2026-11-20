"""Formas de los datos que recibe el backend y sus validaciones."""

import re

from pydantic import BaseModel, field_validator

PATRON_CORREO = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


class RegistroEntrada(BaseModel):
    nombre: str
    telefono: str
    correo: str

    @field_validator("nombre")
    @classmethod
    def validar_nombre(cls, valor: str) -> str:
        valor = " ".join(valor.split())
        if len(valor) > 120:
            raise ValueError("El nombre es demasiado largo.")
        if len(valor) < 5 or " " not in valor:
            raise ValueError("Escribe tu nombre completo (nombre y apellido).")
        return valor

    @field_validator("telefono")
    @classmethod
    def validar_telefono(cls, valor: str) -> str:
        digitos = re.sub(r"\D", "", valor)
        if len(digitos) == 12 and digitos.startswith("52"):
            digitos = digitos[2:]
        if len(digitos) != 10:
            raise ValueError("El teléfono debe tener 10 dígitos.")
        return digitos

    @field_validator("correo")
    @classmethod
    def validar_correo(cls, valor: str) -> str:
        valor = valor.strip().lower()
        if len(valor) > 120 or not PATRON_CORREO.match(valor):
            raise ValueError("Escribe un correo válido.")
        return valor