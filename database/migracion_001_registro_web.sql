USE estacionamiento;

ALTER TABLE personas
    ADD COLUMN telefono VARCHAR(20) NULL AFTER nombre,
    ADD COLUMN correo VARCHAR(120) NULL AFTER telefono,
    ADD COLUMN estado ENUM('pendiente', 'aprobado', 'rechazado')
        NOT NULL DEFAULT 'aprobado' AFTER correo,
    ADD UNIQUE KEY uq_personas_correo (correo);

ALTER TABLE rostros
    ADD COLUMN angulo ENUM('frente', 'izquierda', 'derecha') NULL AFTER modelo;