# core/middleware.py
import uuid
from django.utils.deprecation import MiddlewareMixin
from django.db import connection

class PgAuditContext(MiddlewareMixin):
    def process_request(self, request):
        rid = str(uuid.uuid4())
        user = request.user.username if getattr(request, "user", None) and request.user.is_authenticated else "anon"

        # intenta tomar IP real (por si hay proxy), con fallback a REMOTE_ADDR:
        ip = (request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip()
              or request.META.get("REMOTE_ADDR") or "")

        with connection.cursor() as cur:
            # aparecerá en logs PG y lo puedes ver en audit_ping
            cur.execute("SET application_name = %s;", [f"NUAM:{user}:{rid}"])
            # OJO: tercer argumento en FALSE -> sesión (no solo transacción)
            cur.execute("SELECT set_config('nuam.user', %s, false);", [user])
            cur.execute("SELECT set_config('nuam.request_id', %s, false);", [rid])
            cur.execute("SELECT set_config('nuam.ip', %s, false);", [ip])
