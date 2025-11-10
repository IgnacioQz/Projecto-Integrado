"""
Middleware que etiqueta la sesión de PostgreSQL con:
- application_name = "NUAM:{user}:{uuid}"
- GUCs: nuam.user, nuam.request_id, nuam.ip  (nivel SESIÓN)
Esto permite que los triggers de auditoría capten 'quién/desde dónde' actuó.
"""
import uuid
from django.utils.deprecation import MiddlewareMixin
from django.db import connection

class PgAuditContext(MiddlewareMixin):
    def process_request(self, request):
        rid  = str(uuid.uuid4())
        user = request.user.username if getattr(request, "user", None) and request.user.is_authenticated else "anon"
        ip   = (request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip()
                or request.META.get("REMOTE_ADDR") or "")

        with connection.cursor() as cur:
            # Lo verás en pg_stat_activity y en /audit-ping/
            cur.execute("SET application_name = %s;", [f"NUAM:{user}:{rid}"])
            # 'false' => persistente a nivel de sesión (no solo transacción)
            cur.execute("SELECT set_config('nuam.user', %s, false);", [user])
            cur.execute("SELECT set_config('nuam.request_id', %s, false);", [rid])
            cur.execute("SELECT set_config('nuam.ip', %s, false);", [ip])
