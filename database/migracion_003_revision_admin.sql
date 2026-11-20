USE estacionamiento;

ALTER TABLE personas
    ADD COLUMN motivo_rechazo VARCHAR(500) NULL AFTER token_registro,
    ADD COLUMN revisado_en DATETIME NULL AFTER motivo_rechazo;