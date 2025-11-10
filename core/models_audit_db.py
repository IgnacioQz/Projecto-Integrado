"""
Modelo "unmanaged" que mapea la tabla de auditoría en PostgreSQL:
audit.events  ->  "audit"."events" (schema + tabla)
NO crea ni migra la tabla; solo permite leerla desde Django ORM.
"""
from django.db import models

class AuditEventDB(models.Model):
    # Identificador del evento (UUID generado en el trigger)
    event_id     = models.UUIDField(primary_key=True)

    # Momento del cambio
    changed_at   = models.DateTimeField()

    # Metadatos del origen del cambio
    table_schema = models.CharField(max_length=64)
    table_name   = models.CharField(max_length=64)   # p.ej. TBL_CALIFICACION or TBL_FACTOR_VALOR
    op           = models.CharField(max_length=1)    # 'I', 'U', 'D'
    row_pk       = models.CharField(max_length=128)  # PK de la fila afectada en la tabla de negocio

    # Quien ejecuta en la BD (siempre será el usuario de conexión, p.ej. nuam_user)
    db_user      = models.CharField(max_length=128)

    # Metadatos inyectados por el middleware (aplicación)
    app_name     = models.CharField(max_length=256, null=True, blank=True)  # application_name
    app_user     = models.CharField(max_length=128, null=True, blank=True)  # usuario Django
    request_id   = models.CharField(max_length=128, null=True, blank=True)  # UUID por request
    client_ip    = models.CharField(max_length=64,  null=True, blank=True)  # IP del request

    # Estado antes y después (JSON) según operación
    before_row   = models.JSONField(null=True, blank=True)
    after_row    = models.JSONField(null=True, blank=True)

    class Meta:
        managed  = False  # <- IMPORTANTÍSIMO: no crear ni migrar
        db_table = 'audit"."events'  # <- truco para que Django cite "audit"."events"
        ordering = ['-changed_at']   # default (sobre-escrito en la vista)
