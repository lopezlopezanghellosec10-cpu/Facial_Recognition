USE estacionamiento;

ALTER TABLE personas
    ADD COLUMN token_registro CHAR(64) NULL AFTER estado;

ALTER TABLE rostros
    ADD UNIQUE KEY uq_rostros_persona_angulo (persona_id, angulo);