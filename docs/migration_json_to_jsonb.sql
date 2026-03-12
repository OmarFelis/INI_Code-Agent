-- Migration: JSON → JSONB en scan_jobs
-- Ejecutar en la BD A-ONE (schema code_agent o public según configuración)
-- Solo necesario si la tabla scan_jobs ya existe con columnas JSON

ALTER TABLE scan_jobs
    ALTER COLUMN failed_files TYPE JSONB USING failed_files::jsonb,
    ALTER COLUMN results      TYPE JSONB USING results::jsonb;

-- Índice GIN opcional para búsquedas dentro de results (ej: por microservice_name, status)
-- CREATE INDEX CONCURRENTLY idx_scan_jobs_results ON scan_jobs USING GIN (results);
