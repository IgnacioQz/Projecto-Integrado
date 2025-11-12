from django.db import migrations

# --- SQL de instalación (idempotente) ---
CREATE_SQL = r"""
BEGIN;

-- 1) Esquema de auditoría
CREATE SCHEMA IF NOT EXISTS audit;

-- 2) Tabla de eventos
CREATE TABLE IF NOT EXISTS audit.events (
  id           BIGSERIAL PRIMARY KEY,
  changed_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  table_schema TEXT NOT NULL,
  table_name   TEXT NOT NULL,
  op           CHAR(1) NOT NULL,           -- I/U/D
  row_pk       TEXT,                        -- PK relevante (calificacion_id o id)
  app_name     TEXT,
  app_user     TEXT,
  request_id   TEXT,
  client_ip    TEXT,
  db_user      TEXT,
  before_row   JSONB,
  after_row    JSONB
);

-- 3) Función auditora (genérica; toma PK desde JSON de OLD/NEW)
CREATE OR REPLACE FUNCTION audit.f_log_row_change()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
  v_pk_val TEXT;
  v_before JSONB;
  v_after  JSONB;
BEGIN
  -- OLD/NEW a JSONB (para extraer claves sin conocer nombres)
  IF TG_OP IN ('INSERT','UPDATE') THEN
    v_after := to_jsonb(NEW);
  END IF;
  IF TG_OP IN ('UPDATE','DELETE') THEN
    v_before := to_jsonb(OLD);
  END IF;

  -- PK: primero 'calificacion_id', si no existe usa 'id'
  IF TG_OP = 'DELETE' THEN
    v_pk_val := COALESCE(v_before->>'calificacion_id', v_before->>'id');
  ELSE
    v_pk_val := COALESCE(v_after->>'calificacion_id', v_after->>'id');
  END IF;

  INSERT INTO audit.events(
    table_schema, table_name, op, row_pk,
    app_name, app_user, request_id, client_ip, db_user,
    before_row, after_row
  )
  VALUES (
    TG_TABLE_SCHEMA, TG_TABLE_NAME, SUBSTRING(TG_OP,1,1), v_pk_val,
    current_setting('application_name', true),
    current_setting('nuam.user', true),
    current_setting('nuam.request_id', true),
    current_setting('nuam.ip', true),
    current_user,
    v_before, v_after
  );

  IF TG_OP = 'DELETE' THEN
    RETURN OLD;
  ELSE
    RETURN NEW;
  END IF;
END;
$$;

-- 4) Triggers (crear solo si no existen)
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_audit_calificacion') THEN
    EXECUTE '
      CREATE TRIGGER trg_audit_calificacion
      AFTER INSERT OR UPDATE OR DELETE ON "TBL_CALIFICACION"
      FOR EACH ROW EXECUTE FUNCTION audit.f_log_row_change()';
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_audit_factor_valor') THEN
    EXECUTE '
      CREATE TRIGGER trg_audit_factor_valor
      AFTER INSERT OR UPDATE OR DELETE ON "TBL_FACTOR_VALOR"
      FOR EACH ROW EXECUTE FUNCTION audit.f_log_row_change()';
  END IF;
END$$;

-- 5) Permisos de dev (en prod cambien PUBLIC por el rol de la app)
GRANT USAGE ON SCHEMA audit TO PUBLIC;
GRANT SELECT, INSERT ON audit.events TO PUBLIC;

COMMIT;
"""

# --- SQL de reversa (NO borra la tabla por defecto; quita triggers de forma segura) ---
ROLLBACK_SQL = r"""
BEGIN;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_trigger WHERE tgname='trg_audit_calificacion') THEN
    EXECUTE 'DROP TRIGGER trg_audit_calificacion ON "TBL_CALIFICACION"';
  END IF;
  IF EXISTS (SELECT 1 FROM pg_trigger WHERE tgname='trg_audit_factor_valor') THEN
    EXECUTE 'DROP TRIGGER trg_audit_factor_valor ON "TBL_FACTOR_VALOR"';
  END IF;
END$$;

-- Si quieren limpiar TODO al revertir, descomenten:
-- DROP FUNCTION IF EXISTS audit.f_log_row_change() CASCADE;
-- DROP TABLE IF EXISTS audit.events;
-- DROP SCHEMA IF EXISTS audit;

COMMIT;
"""

class Migration(migrations.Migration):

    dependencies = [
        ('core', '0002_seed_factor_def'),  # ajusta si tu último archivo tiene otro nombre
    ]

    operations = [
        migrations.RunSQL(sql=CREATE_SQL, reverse_sql=ROLLBACK_SQL),
    ]