"""Límite sencillo de peticiones por IP, guardado en memoria."""

import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request


class Limitador:
    """Permite como máximo `maximo` peticiones por IP cada `ventana` segundos."""

    def __init__(self, maximo: int, ventana: int):
        self.maximo = maximo
        self.ventana = ventana
        self._intentos: dict[str, deque] = defaultdict(deque)
        self._candado = threading.Lock()

    def permitir(self, clave: str, ahora: float | None = None) -> bool:
        ahora = time.monotonic() if ahora is None else ahora
        with self._candado:
            cola = self._intentos[clave]
            while cola and ahora - cola[0] > self.ventana:
                cola.popleft()
            if len(cola) >= self.maximo:
                return False
            cola.append(ahora)
            return True

    def __call__(self, request: Request) -> None:
        ip = request.client.host if request.client else "desconocida"
        if not self.permitir(ip):
            raise HTTPException(
                status_code=429,
                detail="Demasiadas peticiones. Intenta de nuevo en unos minutos.",
            )