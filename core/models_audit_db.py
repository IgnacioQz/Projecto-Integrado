# =============================================================================
# models_audit.py — Modelo unmanaged para tabla de auditoría en PostgreSQL
# =============================================================================
# Mapea: schema "audit", tabla "events"  →  "audit"."events"
# Importante: managed = False  → Django NO crea ni migra esta tabla.
# -----------------------------------------------------------------------------

from django.db import models


class AuditEventDB(models.Model):
    """
    Evento de auditoría capturado por triggers en BD.
    - Lectura solamente (unmanaged).
    - Guarda quién/qué/cuándo cambió una fila de negocio y su antes/después.
    """

    # Identificador del evento (UUID generado en el trigger de la BD)
    id = models.UUIDField(primary_key=True)

    # Momento exacto del cambio
    changed_at = models.DateTimeField()

    # Origen del cambio (tabla/operación/fila afectada)
    table_schema = models.CharField(max_length=64)
    table_name   = models.CharField(max_length=64)   # p.ej. TBL_CALIFICACION / TBL_FACTOR_VALOR
    op           = models.CharField(                 # operación: Insert/Update/Delete
        max_length=1,
        choices=[("I", "Insert"), ("U", "Update"), ("D", "Delete")],
    )
    row_pk       = models.CharField(max_length=128)  # PK de la fila afectada (texto)

    # Usuario de BD (cuenta técnica con la que se conectó la app)
    db_user = models.CharField(max_length=128)

    # Metadatos de aplicación (inyectados por middleware a GUCs/headers)
    app_name   = models.CharField(max_length=256, null=True, blank=True)  # application_name
    app_user   = models.CharField(max_length=128, null=True, blank=True)  # usuario Django
    request_id = models.CharField(max_length=128, null=True, blank=True)  # UUID por request
    client_ip  = models.CharField(max_length=64,  null=True, blank=True)  # IP del request

    # Estado antes y después en formato JSON (según op)
    before_row = models.JSONField(null=True, blank=True)
    after_row  = models.JSONField(null=True, blank=True)

    class Meta:
        # IMPORTANTÍSIMO: no crear ni migrar esta tabla desde Django.
        managed = False

        # Truco para que Django cite con schema y tabla: "audit"."events"
        db_table = 'audit"."events'

        # Orden por defecto (normalmente se sobreescribe en la vista)
        ordering = ["-changed_at"]

        verbose_name = "Evento de Auditoría"
        verbose_name_plural = "Eventos de Auditoría"

        # (Opcional) Si la tabla tiene índices en BD ya creados, no los declares aquí.
        # Django no los gestionará al ser unmanaged.

    def __str__(self) -> str:
        """Representación legible: <YYYY-mm-dd HH:MM:SS> OP schema.table pk"""
        ts = self.changed_at.isoformat(sep=" ", timespec="seconds") if self.changed_at else "?"
        return f"[{ts}] {self.op} {self.table_schema}.{self.table_name} pk={self.row_pk}"
