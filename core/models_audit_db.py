from django.db import models

class AuditEventDB(models.Model):
    event_id     = models.UUIDField(primary_key=True)
    changed_at   = models.DateTimeField()
    table_schema = models.CharField(max_length=64)
    table_name   = models.CharField(max_length=64)
    op           = models.CharField(max_length=1)
    row_pk       = models.CharField(max_length=128)
    db_user      = models.CharField(max_length=128)
    app_name     = models.CharField(max_length=256, null=True, blank=True)
    app_user     = models.CharField(max_length=128, null=True, blank=True)
    request_id   = models.CharField(max_length=128, null=True, blank=True)
    client_ip    = models.CharField(max_length=64,  null=True, blank=True)
    before_row   = models.JSONField(null=True, blank=True)
    after_row    = models.JSONField(null=True, blank=True)

    class Meta:
        managed = False
        # ⚠️ Usa schema+tabla correctamente citados:
        db_table = 'audit"."events'
        ordering = ['-changed_at']
