# core/views_audit.py
from django.contrib.auth.decorators import login_required, user_passes_test
from django.shortcuts import render
from django.db.models import Q
from django.db import connection
from django.http import JsonResponse

from .models_audit_db import AuditEventDB

def _is_analista_o_admin(u):
    return (
        u.is_superuser or
        u.groups.filter(name__in=["Administrador", "AnalistaTributario"]).exists()
    )

@login_required(login_url="login")
@user_passes_test(_is_analista_o_admin)
def auditoria_list(request):
    q = AuditEventDB.objects.all()

    # Filtros simples (opcionales)
    tabla = request.GET.get('tabla', '')           # p.ej. TBL_CALIFICACION
    op    = request.GET.get('op', '')              # I/U/D
    actor = request.GET.get('actor', '')           # app_user
    pk    = request.GET.get('pk', '')              # row_pk
    rid   = request.GET.get('rid', '')             # request_id
    fi    = request.GET.get('fi', '')              # YYYY-MM-DD
    ff    = request.GET.get('ff', '')              # YYYY-MM-DD

    if tabla:
        q = q.filter(table_name__iexact=tabla)
    if op in ('I','U','D'):
        q = q.filter(op=op)
    if actor:
        q = q.filter(app_user__icontains=actor)
    if pk:
        q = q.filter(row_pk=pk)
    if rid:
        q = q.filter(request_id=rid)
    if fi:
        q = q.filter(changed_at__date__gte=fi)
    if ff:
        q = q.filter(changed_at__date__lte=ff)

    eventos = q.order_by('-changed_at')[:500]
    return render(request, "auditoria/lista_log.html", {"eventos": eventos})

@login_required(login_url="login")
def audit_ping(request):
    """Verifica que el middleware está seteando las GUCs y application_name."""
    with connection.cursor() as cur:
        cur.execute("""
            SELECT current_setting('application_name', true),
                   current_setting('nuam.user', true),
                   current_setting('nuam.request_id', true),
                   current_setting('nuam.ip', true)
        """)
        appname, user, rid, ip = cur.fetchone()
    return JsonResponse({
        "application_name": appname,
        "nuam.user": user,
        "nuam.request_id": rid,
        "nuam.ip": ip
    })
