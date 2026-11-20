"""Consultas a la base de datos del registro web."""

from mysql.connector import IntegrityError

from database.connection import get_connection

ANGULOS = ("frente", "izquierda", "derecha")


class CorreoDuplicado(Exception):
    """El correo ya existe en la tabla personas."""


# ---------------------------------------------------------------- registro

def crear_persona_pendiente(
    nombre: str, telefono: str, correo: str, token_hash: str
) -> int:
    """Crea una persona pendiente de aprobación y devuelve su id.

    Si el correo ya existía pero fue rechazado, esa misma fila vuelve a quedar
    pendiente (la persona está reintentando). Con cualquier otro estado, el
    correo se considera repetido.
    """
    connection = get_connection()
    cursor = connection.cursor()

    try:
        try:
            cursor.execute(
                """
                INSERT INTO personas
                    (nombre, telefono, correo, estado, activa, token_registro)
                VALUES (%s, %s, %s, 'pendiente', FALSE, %s)
                """,
                (nombre, telefono, correo, token_hash),
            )
            connection.commit()
            return cursor.lastrowid
        except IntegrityError as error:
            connection.rollback()
            if error.errno != 1062:
                raise

        cursor.execute(
            "SELECT id FROM personas WHERE correo = %s AND estado = 'rechazado'",
            (correo,),
        )
        fila = cursor.fetchone()
        if fila is None:
            raise CorreoDuplicado
        persona_id = fila[0]

        cursor.execute("DELETE FROM rostros WHERE persona_id = %s", (persona_id,))
        cursor.execute(
            """
            UPDATE personas
            SET nombre = %s, telefono = %s, estado = 'pendiente', activa = FALSE,
                token_registro = %s, motivo_rechazo = NULL, revisado_en = NULL
            WHERE id = %s
            """,
            (nombre, telefono, token_hash, persona_id),
        )
        connection.commit()
        return persona_id
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()
        connection.close()


def obtener_hash_token(persona_id: int) -> str | None:
    """Devuelve el hash del token de una persona que sigue pendiente.

    Si la persona no existe o ya no está pendiente, devuelve None.
    """
    connection = get_connection()
    cursor = connection.cursor()

    try:
        cursor.execute(
            """
            SELECT token_registro FROM personas
            WHERE id = %s AND estado = 'pendiente'
            """,
            (persona_id,),
        )
        fila = cursor.fetchone()
        return fila[0] if fila else None
    finally:
        cursor.close()
        connection.close()


def obtener_estado_registro(persona_id: int) -> dict | None:
    """Estado de un registro para que la propia persona lo consulte con su token."""
    connection = get_connection()
    cursor = connection.cursor(dictionary=True)

    try:
        cursor.execute(
            """
            SELECT estado, motivo_rechazo, token_registro
            FROM personas WHERE id = %s
            """,
            (persona_id,),
        )
        fila = cursor.fetchone()
        if fila is None:
            return None

        cursor.execute(
            "SELECT angulo FROM rostros WHERE persona_id = %s AND angulo IS NOT NULL",
            (persona_id,),
        )
        angulos = [f["angulo"] for f in cursor.fetchall()]
        return {
            "estado": fila["estado"],
            "motivo_rechazo": fila["motivo_rechazo"],
            "token_hash": fila["token_registro"],
            "faltan": [a for a in ANGULOS if a not in angulos],
        }
    finally:
        cursor.close()
        connection.close()


# ----------------------------------------------------------------- rostros

def guardar_rostro(persona_id: int, angulo: str, descriptor: bytes) -> list[str]:
    """Guarda (o reemplaza) el rostro de un ángulo y devuelve los ángulos ya guardados."""
    connection = get_connection()
    cursor = connection.cursor()

    try:
        cursor.execute(
            """
            INSERT INTO rostros (persona_id, descriptor_facial, modelo, angulo)
            VALUES (%s, %s, 'SFace', %s)
            ON DUPLICATE KEY UPDATE descriptor_facial = VALUES(descriptor_facial)
            """,
            (persona_id, descriptor, angulo),
        )
        connection.commit()

        cursor.execute(
            "SELECT angulo FROM rostros WHERE persona_id = %s AND angulo IS NOT NULL",
            (persona_id,),
        )
        return [fila[0] for fila in cursor.fetchall()]
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()
        connection.close()


def obtener_descriptores(persona_id: int, excepto: str | None = None) -> list[bytes]:
    """Descriptores SFace de una persona; opcionalmente sin el de un ángulo."""
    connection = get_connection()
    cursor = connection.cursor()

    try:
        if excepto is None:
            cursor.execute(
                """
                SELECT descriptor_facial FROM rostros
                WHERE persona_id = %s AND modelo = 'SFace'
                """,
                (persona_id,),
            )
        else:
            cursor.execute(
                """
                SELECT descriptor_facial FROM rostros
                WHERE persona_id = %s AND modelo = 'SFace'
                  AND (angulo IS NULL OR angulo <> %s)
                """,
                (persona_id, excepto),
            )
        return [bytes(fila[0]) for fila in cursor.fetchall()]
    finally:
        cursor.close()
        connection.close()


def obtener_descriptores_ajenos(persona_id: int) -> list[dict]:
    """Descriptores de las demás personas pendientes o aprobadas."""
    connection = get_connection()
    cursor = connection.cursor(dictionary=True)

    try:
        cursor.execute(
            """
            SELECT p.id, p.nombre, p.estado, r.descriptor_facial
            FROM rostros r
            INNER JOIN personas p ON p.id = r.persona_id
            WHERE p.id <> %s
              AND p.estado IN ('pendiente', 'aprobado')
              AND r.modelo = 'SFace'
            """,
            (persona_id,),
        )
        return [
            {
                "persona_id": fila["id"],
                "nombre": fila["nombre"],
                "estado": fila["estado"],
                "descriptor": bytes(fila["descriptor_facial"]),
            }
            for fila in cursor.fetchall()
        ]
    finally:
        cursor.close()
        connection.close()


# ------------------------------------------------------------------- admin

def _con_fotos(persona: dict, angulos: list[str]) -> dict:
    """Agrega a la persona qué fotos tiene y cuáles le faltan."""
    persona["fotos"] = {a: a in angulos for a in ANGULOS}
    persona["faltan"] = [a for a in ANGULOS if a not in angulos]
    return persona


def listar_por_estado(estado: str) -> list[dict]:
    """Personas de un estado, con sus datos y el estado de sus fotos.

    Los pendientes salen del más antiguo al más nuevo (fila de espera);
    los demás, del más reciente al más antiguo.
    """
    connection = get_connection()
    cursor = connection.cursor(dictionary=True)

    try:
        cursor.execute(
            """
            SELECT id, nombre, telefono, correo, estado, motivo_rechazo,
                   creada_en, revisado_en
            FROM personas
            WHERE estado = %s
            ORDER BY creada_en
            """,
            (estado,),
        )
        personas = cursor.fetchall()
        if estado != "pendiente":
            personas.reverse()

        cursor.execute(
            """
            SELECT persona_id, angulo FROM rostros
            WHERE angulo IS NOT NULL
              AND persona_id IN (SELECT id FROM personas WHERE estado = %s)
            """,
            (estado,),
        )
        angulos_por_persona: dict[int, list[str]] = {}
        for fila in cursor.fetchall():
            angulos_por_persona.setdefault(fila["persona_id"], []).append(
                fila["angulo"]
            )

        return [_con_fotos(p, angulos_por_persona.get(p["id"], [])) for p in personas]
    finally:
        cursor.close()
        connection.close()


def contar_por_estado() -> dict[str, int]:
    """Cuántas personas hay en cada estado."""
    connection = get_connection()
    cursor = connection.cursor()

    try:
        cursor.execute("SELECT estado, COUNT(*) FROM personas GROUP BY estado")
        conteo = {"pendiente": 0, "aprobado": 0, "rechazado": 0}
        for estado, total in cursor.fetchall():
            conteo[estado] = total
        return conteo
    finally:
        cursor.close()
        connection.close()


def obtener_persona(persona_id: int) -> dict | None:
    """Devuelve todos los datos de una persona (o None si no existe)."""
    connection = get_connection()
    cursor = connection.cursor(dictionary=True)

    try:
        cursor.execute(
            """
            SELECT id, nombre, telefono, correo, estado,
                   motivo_rechazo, creada_en, revisado_en
            FROM personas
            WHERE id = %s
            """,
            (persona_id,),
        )
        persona = cursor.fetchone()
        if persona is None:
            return None

        cursor.execute(
            "SELECT angulo FROM rostros WHERE persona_id = %s AND angulo IS NOT NULL",
            (persona_id,),
        )
        angulos = [fila["angulo"] for fila in cursor.fetchall()]
        return _con_fotos(persona, angulos)
    finally:
        cursor.close()
        connection.close()


def _cambiar_estado(
    persona_id: int, desde: str, hacia: str, activa: bool, motivo: str | None
) -> bool:
    """Cambia el estado solo si la persona sigue en el estado `desde`."""
    connection = get_connection()
    cursor = connection.cursor()

    try:
        cursor.execute(
            """
            UPDATE personas
            SET estado = %s, activa = %s, motivo_rechazo = %s, revisado_en = NOW()
            WHERE id = %s AND estado = %s
            """,
            (hacia, activa, motivo, persona_id, desde),
        )
        connection.commit()
        return cursor.rowcount == 1
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()
        connection.close()


def aprobar_persona(persona_id: int) -> bool:
    """pendiente -> aprobado (y activa para la cámara)."""
    return _cambiar_estado(persona_id, "pendiente", "aprobado", True, None)


def rechazar_persona(persona_id: int, motivo: str) -> bool:
    """pendiente -> rechazado, con el mensaje para la persona."""
    return _cambiar_estado(persona_id, "pendiente", "rechazado", False, motivo)


def revocar_persona(persona_id: int, motivo: str) -> bool:
    """aprobado -> rechazado: le quita el acceso a alguien ya aprobado."""
    return _cambiar_estado(persona_id, "aprobado", "rechazado", False, motivo)