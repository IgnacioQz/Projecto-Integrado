"""
Auditoría:
- Filtros: op (I/U/D), rango fechas (fi/ff), origen (manual/masiva)
- Agrupación: SIEMPRE por Calificación (PK)
- Métricas: conteos por tipo y usuarios activos
- Ping: /audit-ping/ para diagnosticar GUCs
"""
from itertools import groupby
import json
import os

from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.files.storage import default_storage
from django.core.paginator import Paginator
from django.db import connection
from django.http import JsonResponse, FileResponse, Http404
from django.shortcuts import render, get_object_or_404
from django.utils.timezone import localtime

from core.models_audit_db import AuditEventDB
from core.models import TblArchivoFuente, TblCalificacion

# ============================================================================
# CONFIGURACIÓN (IDs de tipo de ingreso por origen)
# Ajusta estos sets a tus IDs reales de TBL_TIPO_INGRESO.
# ============================================================================
ORIGEN_MANUAL_TIPO_IDS = {1}   # p.ej. "Corredor"
ORIGEN_MASIVA_TIPO_IDS = {2}   # p.ej. {2}  "Para Carga Masiva"


# ============================================================================
# AUTORIZACIÓN
# ============================================================================
def _is_analista_o_admin(u):
    """Permite acceso a superuser, Administrador o AnalistaTributario."""
    return u.is_superuser or u.groups.filter(
        name__in=["Administrador", "AnalistaTributario"]
    ).exists()


# ============================================================================
# HELPERS (UI y BD)
# ============================================================================
def _badge(op: str):
    """Etiqueta + color Bootstrap para la operación."""
    return {
        "I": ("Añadido",   "success"),
        "U": ("Modificado","warning"),
        "D": ("Eliminado", "danger"),
    }.get(op, (op, "secondary"))


def _fetch_calif_ids_by_origen(origen: str) -> set[int]:
    """
    Devuelve calificacion_id según 'origen':
    - 'manual' -> tipo_ingreso_id en ORIGEN_MANUAL_TIPO_IDS
    - 'masiva' -> tipo_ingreso_id en ORIGEN_MASIVA_TIPO_IDS
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


def _fetch_factor_to_calif_map(factor_ids: list[int]) -> dict[int, int]:
    """
    Mapa: id(TBL_FACTOR_VALOR) -> calificacion_id.
    Sirve para agrupar eventos de factores por su calificación.
    """
    if not factor_ids:
        return {}
    placeholders = ", ".join(["%s"] * len(factor_ids))
    sql = f'''
        SELECT id, calificacion_id
        FROM "TBL_FACTOR_VALOR"
        WHERE id IN ({placeholders})
    '''
    with connection.cursor() as cur:
        cur.execute(sql, list(factor_ids))
        rows = cur.fetchall()
    return {rid: cid for rid, cid in rows}


# ============================================================================
# VISTA PRINCIPAL (listado/auditoría)
# ============================================================================
@login_required(login_url="login")
@user_passes_test(_is_analista_o_admin)
def auditoria_list(request):
    """
    Auditoría con filtros y agrupación por calificación:
    - Filtros: op (I/U/D), fi/ff, origen (manual/masiva)
    - Agrupa SIEMPRE por PK de calificación
    - Calcula métricas del resultado filtrado
    """
    # --- Filtros desde GET ---
    op     = request.GET.get("op", "").strip().upper()  # I|U|D|''
    origen = request.GET.get("origen", "").strip()       # 'manual'|'masiva'|''
    fi     = request.GET.get("fi", "").strip()           # YYYY-MM-DD
    ff     = request.GET.get("ff", "").strip()           # YYYY-MM-DD

    # Eventos relevantes (calificación y factores)
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

    # Límite defensivo para evitar respuestas gigantes
    base_rows = list(q[:4000])

    # Si hay filtro por origen, obtén calificaciones válidas
    calif_ids_ok = _fetch_calif_ids_by_origen(origen) if origen else set()

    # ------------------------------------------------------------------ #
    # 1) Determinar TODAS las calificaciones afectadas (para ver si
    #    tienen archivo y si son de carga masiva).
    # ------------------------------------------------------------------ #
    calif_ids_all: set[int] = set()
    for e in base_rows:
        if e.table_name == "TBL_CALIFICACION":
            try:
                calif_ids_all.add(int(e.row_pk))
            except (TypeError, ValueError):
                pass

    # Mapa de factor -> calificación (para agrupar correctamente)
    factor_ids = [int(e.row_pk) for e in base_rows if e.table_name == "TBL_FACTOR_VALOR"]
    f2c = _fetch_factor_to_calif_map(factor_ids)

    # Los factores también apuntan a calificaciones
    calif_ids_all.update(f2c.values())

    # Bulk query: info de archivo/tipo_ingreso por calificación
    calif_fileinfo: dict[int, dict] = {}
    if calif_ids_all:
        for cid, archivo_fuente_id, tipo_ingreso_id in TblCalificacion.objects.filter(
            calificacion_id__in=calif_ids_all
        ).values_list("calificacion_id", "archivo_fuente_id", "tipo_ingreso_id"):
            calif_fileinfo[cid] = {
                "has_file": archivo_fuente_id is not None,
                "is_masiva": tipo_ingreso_id in ORIGEN_MASIVA_TIPO_IDS,
            }

    # Normaliza filas para la UI
    rows = []
    for e in base_rows:
        # Aplica filtro de origen
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
            # Sin filtro de origen: para FACTOR, muestra su calificación
            if e.table_name == "TBL_FACTOR_VALOR":
                pk_visible = f2c.get(int(e.row_pk), "—")
            else:
                pk_visible = e.row_pk

        label, color = _badge(e.op)

        # ¿Esta fila corresponde a una calificación con archivo masivo?
        has_archivo = False
        try:
            cid_int = int(pk_visible)
        except (TypeError, ValueError):
            cid_int = None

        if cid_int is not None:
            info = calif_fileinfo.get(cid_int)
            if info and info["has_file"] and info["is_masiva"]:
                has_archivo = True

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
            "has_archivo": has_archivo,  # 👈 flag para el template
        })

    # --- Métricas (sobre 'rows' ya filtradas) ---
    total_ops = len(rows)
    count_I   = sum(1 for r in rows if r["op"] == "I")
    count_U   = sum(1 for r in rows if r["op"] == "U")
    count_D   = sum(1 for r in rows if r["op"] == "D")
    active_users = sorted({r["actor"] for r in rows if r["actor"] and r["actor"] != "—"})
    active_users_count = len(active_users)

    # --- Agrupación por Calificación (PK) ---
    keyfunc       = lambda r: r["pk"]
    group_title   = lambda k: f"Calificación #{k}"
    empty_key_lbl = "Calificación (sin PK)"

    # Orden estable: por PK (str) y luego por fecha DESC (para groupby)
    rows_sorted = sorted(
        rows,
        key=lambda r: (str(keyfunc(r) or ""), -r["when"].timestamp())
    )

    groups = []
    for gkey, items_iter in groupby(rows_sorted, keyfunc):
        items = list(items_iter)
        items.sort(key=lambda r: r["when"])  # timeline ASC dentro del grupo
        groups.append({
            "key": gkey or empty_key_lbl,
            "title": group_title(gkey or empty_key_lbl),
            "first_when": items[0]["when"] if items else None,
            "last_when":  items[-1]["when"] if items else None,
            "count": len(items),
            "items": items,
        })

    # --- Paginación (10 grupos por página) ---
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
        "active_users": active_users[:8],  # top visibles
    }
    return render(request, "auditoria/lista_log.html", context)


# ============================================================================
# DESCARGAR ARCHIVO FUENTE (S3 / legacy)
# ============================================================================
@login_required(login_url="login")
@user_passes_test(_is_analista_o_admin)
def descargar_archivo_fuente(request, calificacion_id: int):
    """
    Descarga el archivo fuente asociado a una calificación.
    - Busca la TblCalificacion por PK.
    - Usa su FK archivo_fuente_id para encontrar TblArchivoFuente.
    - Si existe FileField (`archivo`), lo sirve directamente desde S3.
    - Si no, intenta reconstruir la key desde `ruta_almacenamiento` (legacy).
    """
    # 1) Buscar la calificación
    calif = get_object_or_404(TblCalificacion, pk=calificacion_id)

    # 2) Tomar el archivo fuente asociado
    af = calif.archivo_fuente
    if af is None:
        raise Http404("No existe archivo fuente asociado a esta calificación.")

    # DEBUG opcional
    print("DEBUG descargar_archivo_fuente: calificacion_id =", calificacion_id)
    print("  archivo_fuente_id:", af.archivo_fuente_id)
    print("  archivo.name:", getattr(af.archivo, "name", None))
    print("  ruta_almacenamiento:", af.ruta_almacenamiento)

    # --- Caso 1: FileField (nuevo flujo con S3) ---
    if getattr(af, "archivo", None) and af.archivo.name:
        f = af.archivo.open("rb")  # usa S3Boto3Storage
        filename = af.nombre_archivo or os.path.basename(af.archivo.name)
        return FileResponse(
            f,
            as_attachment=True,
            filename=filename,
        )

    # --- Caso 2: sólo tenemos la URL en ruta_almacenamiento (legacy) ---
    if af.ruta_almacenamiento:
        url = af.ruta_almacenamiento.strip()

        key = None
        marker = ".amazonaws.com/"
        if marker in url:
            key = url.split(marker, 1)[1]

        if key:
            try:
                f = default_storage.open(key, "rb")
                filename = af.nombre_archivo or os.path.basename(key)
                return FileResponse(
                    f,
                    as_attachment=True,
                    filename=filename,
                )
            except Exception as ex:
                print("DEBUG error abriendo archivo legacy desde S3:", ex)

    # Si llegamos aquí, realmente no tenemos cómo resolver el archivo
    raise Http404("Este registro no tiene archivo asociado")


# ============================================================================
# PING DE DIAGNÓSTICO (opcional)
# ============================================================================
@login_required(login_url="login")
def audit_ping(request):
    """Devuelve JSON con GUCs seteados (útil para debug del middleware)."""
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
        "db_user": db_user,
    })
