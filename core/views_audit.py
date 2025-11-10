"""
Vista de Auditoría:
- Filtros: Operación (I/U/D), Rango de fechas (Desde/Hasta), Tipo de ingreso (Manual / Masiva)
- Agrupación: SIEMPRE por Calificación (PK)
- Panel de métricas: usuarios activos, total de operaciones y conteo por tipo
- Endpoint /audit-ping/ para diagnosticar GUCs (opcional)
"""
from itertools import groupby
import json

from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.paginator import Paginator
from django.db import connection
from django.http import JsonResponse
from django.shortcuts import render
from django.utils.timezone import localtime

from .models_audit_db import AuditEventDB

# ==========================
# Configuración de filtros por TIPO_INGRESO **por ID**
# ==========================
# Ajusta estos sets a tus IDs reales en el catálogo TBL_TIPO_INGRESO.
ORIGEN_MANUAL_TIPO_IDS = {1}   # Carga manual (Corredor) -> ID=1 (según tus datos)
ORIGEN_MASIVA_TIPO_IDS = set() # Para el futuro (p.ej. {2} cuando exista "Archivo")

# ==========================
# Autorización
# ==========================
def _is_analista_o_admin(u):
    """Permite acceso a superuser, Administrador, AnalistaTributario."""
    return u.is_superuser or u.groups.filter(
        name__in=["Administrador", "AnalistaTributario"]
    ).exists()

# ==========================
# Helpers de look & feel
# ==========================
def _badge(op):
    """Mapea operación a etiqueta + color Bootstrap."""
    return {
        "I": ("Añadido",  "success"),
        "U": ("Modificado",  "warning"),
        "D": ("Eliminado",  "danger"),
    }.get(op, (op, "secondary"))

# ==========================
# Helpers de negocio/BD
# ==========================
def _fetch_calif_ids_by_origen(origen):
    """
    Devuelve los calificacion_id que corresponden al 'origen' pedido.
    - 'manual' -> calificaciones con tipo_ingreso_id en ORIGEN_MANUAL_TIPO_IDS
    - 'masiva' -> calificaciones con tipo_ingreso_id en ORIGEN_MASIVA_TIPO_IDS
    - otro/None -> set() (sin filtro)
    """
    if not origen:
        return set()

    if origen == "manual":
        tipo_ids = ORIGEN_MANUAL_TIPO_IDS
    elif origen == "masiva":
        tipo_ids = ORIGEN_MASIVA_TIPO_IDS
    else:
        return set()

    if not tipo_ids:
        return set()

    placeholders = ", ".join(["%s"] * len(tipo_ids))
    sql = f'''
        SELECT c.calificacion_id
        FROM "TBL_CALIFICACION" c
        WHERE c.tipo_ingreso_id IN ({placeholders})
    '''
    with connection.cursor() as cur:
        cur.execute(sql, list(tipo_ids))
        return {row[0] for row in cur.fetchall()}

def _fetch_factor_to_calif_map(factor_ids):
    """
    Mapea id de TBL_FACTOR_VALOR -> calificacion_id.
    Permite filtrar eventos de factores por 'origen' a través de su calificación.
    """
    if not factor_ids:
        return {}
    placeholders = ", ".join(["%s"] * len(factor_ids))
    sql = f'SELECT id, calificacion_id FROM "TBL_FACTOR_VALOR" WHERE id IN ({placeholders})'
    with connection.cursor() as cur:
        cur.execute(sql, list(factor_ids))
        rows = cur.fetchall()
    return {rid: cid for rid, cid in rows}

# ==========================
# Vista principal
# ==========================
@login_required(login_url="login")
@user_passes_test(_is_analista_o_admin)
def auditoria_list(request):
    """
    Auditoría con filtros y agrupación:
    - Filtros: op (I/U/D), fi/ff (fechas), origen (manual/masiva por ID)
    - Agrupación: SIEMPRE por 'pk' (Calificación)
    - Panel de métricas coherente con el resultado filtrado
    """
    # ---- filtros desde GET ----
    op      = request.GET.get("op", "").strip().upper()  # 'I'|'U'|'D'|''(todas)
    origen  = request.GET.get("origen", "").strip()      # 'manual'|'masiva'|''
    fi      = request.GET.get("fi", "").strip()          # YYYY-MM-DD
    ff      = request.GET.get("ff", "").strip()          # YYYY-MM-DD

    # Filtramos SOLO tablas relevantes para calificaciones
    q = AuditEventDB.objects.filter(
        table_name__in=["TBL_CALIFICACION", "TBL_FACTOR_VALOR"]
    )

    if op in ("I", "U", "D"):
        q = q.filter(op=op)
    if fi:
        q = q.filter(changed_at__date__gte=fi)
    if ff:
        q = q.filter(changed_at__date__lte=ff)

    q = q.order_by("-changed_at")

    # Limite defensivo
    base_rows = list(q[:4000])

    # Si hay filtro por 'origen', averiguamos qué calificaciones aplican
    calif_ids_ok = _fetch_calif_ids_by_origen(origen) if origen else set()

    # Map factor_id -> calificacion_id (necesario para agrupar por PK)
    factor_ids = [int(e.row_pk) for e in base_rows if e.table_name == "TBL_FACTOR_VALOR"]
    f2c = _fetch_factor_to_calif_map(factor_ids)

    # Transformación a filas amigables
    rows = []
    for e in base_rows:
        # Filtro por origen si corresponde
        if origen:
            if e.table_name == "TBL_CALIFICACION":
                if int(e.row_pk) not in calif_ids_ok:
                    continue
                pk_visible = e.row_pk
            else:  # TBL_FACTOR_VALOR
                calif_id = f2c.get(int(e.row_pk))
                if calif_id is None or calif_id not in calif_ids_ok:
                    continue
                pk_visible = calif_id
        else:
            # Sin filtro: para FACTOR mostramos su calificación
            if e.table_name == "TBL_FACTOR_VALOR":
                pk_visible = f2c.get(int(e.row_pk), "—")
            else:
                pk_visible = e.row_pk

        label, color = _badge(e.op)
        rows.append({
            "pk": pk_visible,
            "table": e.table_name,
            "op": e.op,
            "op_label": label,
            "op_color": color,
            "actor": e.app_user or "—",
            "db_user": e.db_user,
            "ip": e.client_ip or "—",
            "rid": e.request_id or "—",
            "when": localtime(e.changed_at),
            "before": json.dumps(e.before_row, ensure_ascii=False, indent=2, sort_keys=True) if e.before_row else "",
            "after":  json.dumps(e.after_row,  ensure_ascii=False, indent=2, sort_keys=True) if e.after_row  else "",
        })

    # Panel de métricas (en base a 'rows' ya filtradas)
    total_ops          = len(rows)
    count_I            = sum(1 for r in rows if r["op"] == "I")
    count_U            = sum(1 for r in rows if r["op"] == "U")
    count_D            = sum(1 for r in rows if r["op"] == "D")
    active_users       = sorted({r["actor"] for r in rows if r["actor"] and r["actor"] != "—"})
    active_users_count = len(active_users)

    # ---- agrupación (SIEMPRE por PK) ----
    keyfunc       = lambda r: r["pk"]
    group_title   = lambda k: f"Calificación #{k}"
    empty_key_lbl = "Calificación (sin PK)"

    groups = []
    # FIX: clave como str para evitar comparar int con str al ordenar
    rows_sorted = sorted(
        rows,
        key=lambda r: (str(keyfunc(r) or ""), -r["when"].timestamp())
    )
    for gkey, items_iter in groupby(rows_sorted, keyfunc):
        items = list(items_iter)
        items.sort(key=lambda r: r["when"])  # timeline ASC
        groups.append({
            "key": gkey or empty_key_lbl,
            "title": group_title(gkey or empty_key_lbl),
            "first_when": items[0]["when"] if items else None,
            "last_when":  items[-1]["when"] if items else None,
            "count": len(items),
            "items": items,
        })

    # Paginación de grupos (10 por página)
    paginator   = Paginator(groups, 10)
    page_number = request.GET.get("page")
    page_obj    = paginator.get_page(page_number)

    context = {
        "page_obj": page_obj,
        "total_groups": paginator.count,
        # Filtros (para mantener estado en la UI)
        "op": op, "fi": fi, "ff": ff, "origen": origen,
        # Métricas
        "total_ops": total_ops,
        "count_I": count_I,
        "count_U": count_U,
        "count_D": count_D,
        "active_users_count": active_users_count,
        "active_users": active_users[:8],
    }
    return render(request, "auditoria/lista_log.html", context)

# ==========================
# Ping de diagnóstico (opcional)
# ==========================
@login_required(login_url="login")
def audit_ping(request):
    """Devuelve JSON con los GUCs seteados por el middleware, útil para debug."""
    with connection.cursor() as cur:
        cur.execute("""
            SELECT current_setting('application_name', true),
                   current_setting('nuam.user', true),
                   current_setting('nuam.request_id', true),
                   current_setting('nuam.ip', true),
                   current_user
        """)
        appname, user, rid, ip, db_user = cur.fetchone()
    return JsonResponse({
        "application_name": appname,
        "nuam.user": user,
        "nuam.request_id": rid,
        "nuam.ip": ip,
        "db_user": db_user
    })
