-- Esquema inicial del MVP del estacionamiento (MySQL 5.7+).
-- Ejecuta este archivo desde MySQL Workbench o desde la consola de MySQL.

CREATE DATABASE IF NOT EXISTS estacionamiento
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE estacionamiento;

CREATE TABLE IF NOT EXISTS personas (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    nombre VARCHAR(120) NOT NULL,
    activa BOOLEAN NOT NULL DEFAULT TRUE,
    creada_en TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS rostros (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    persona_id BIGINT UNSIGNED NOT NULL,
    descriptor_facial BLOB NOT NULL,
    modelo VARCHAR(80) NOT NULL DEFAULT 'SFace',
    creado_en TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    INDEX idx_rostros_persona (persona_id),
    CONSTRAINT fk_rostros_personas
        FOREIGN KEY (persona_id) REFERENCES personas (id)
        ON DELETE CASCADE
        ON UPDATE CASCADE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS estancias (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    persona_id BIGINT UNSIGNED NOT NULL,
    entrada DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    salida DATETIME NULL,
    PRIMARY KEY (id),
    INDEX idx_estancias_persona_salida (persona_id, salida),
    CONSTRAINT fk_estancias_personas
        FOREIGN KEY (persona_id) REFERENCES personas (id)
        ON DELETE RESTRICT
        ON UPDATE CASCADE
) ENGINE=InnoDB;
