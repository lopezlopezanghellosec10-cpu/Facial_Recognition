"""Operaciones para guardar personas y sus descriptores faciales."""

from .connection import get_connection


def register_person(name: str, face_descriptor: bytes) -> int:
    """Guarda una persona y su descriptor facial en una sola transacción."""
    connection = get_connection()
    cursor = connection.cursor()

    try:
        cursor.execute(
            "INSERT INTO personas (nombre) VALUES (%s)",
            (name,),
        )
        person_id = cursor.lastrowid

        cursor.execute(
            """
            INSERT INTO rostros (persona_id, descriptor_facial, modelo)
            VALUES (%s, %s, %s)
            """,
            (person_id, face_descriptor, "SFace"),
        )
        connection.commit()
        return person_id
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()
        connection.close()


def get_registered_faces() -> list[tuple[int, str, bytes]]:
    """Devuelve los descriptores SFace de las personas activas."""
    connection = get_connection()
    cursor = connection.cursor()

    try:
        cursor.execute(
            """
            SELECT personas.id, personas.nombre, rostros.descriptor_facial
            FROM personas
            INNER JOIN rostros ON rostros.persona_id = personas.id
            WHERE personas.activa = TRUE AND rostros.modelo = %s
            """,
            ("SFace",),
        )
        return cursor.fetchall()
    finally:
        cursor.close()
        connection.close()
