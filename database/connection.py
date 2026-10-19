"""Conexión de Python con MySQL/MariaDB de XAMPP."""

import os

import mysql.connector
from mysql.connector import Error


def get_connection():
    """Abre y devuelve una conexión a la base de datos del estacionamiento.

    Los valores por defecto corresponden a una instalación local de XAMPP.
    Se pueden sustituir mediante variables de entorno DB_HOST, DB_PORT,
    DB_NAME, DB_USER y DB_PASSWORD.
    """
    try:
        return mysql.connector.connect(
            host=os.getenv("DB_HOST", "127.0.0.1"),
            port=int(os.getenv("DB_PORT", "3306")),
            database=os.getenv("DB_NAME", "estacionamiento"),
            user=os.getenv("DB_USER", "root"),
            password=os.getenv("DB_PASSWORD", ""),
        )
    except Error as error:
        raise ConnectionError(
            "No se pudo conectar a estacionamiento. Revisa que MySQL esté "
            "activo en XAMPP y que las credenciales DB_* sean correctas."
        ) from error


def main() -> None:
    """Permite comprobar manualmente la conexión ejecutando este módulo."""
    connection = get_connection()
    cursor = None
    try:
        cursor = connection.cursor()
        cursor.execute("SELECT DATABASE()")
        database_name = cursor.fetchone()[0]
        print(f"Conexión correcta a la base de datos: {database_name}")
    finally:
        if cursor is not None:
            cursor.close()
        connection.close()


if __name__ == "__main__":
    main()
