from __future__ import annotations

# ============================================================================
# IMPORTS
# ============================================================================
import os
from io import TextIOWrapper
from decimal import Decimal as D

import pdfplumber
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.db import transaction
from django.shortcuts import render, redirect

from core.models import (
    TblCalificacion, TblFactorValor, TblArchivoFuente, TblTipoIngreso
)

from core.views.mainv import _round8, _build_def_map, POS_MIN, POS_BASE_MAX, POS_MAX
from core.ingestion_helpers import (
    to_int, to_dec, is_monto_col, is_factor_col,
    find_mercado, tipo_ingreso_by_id,
    parse_csv, parse_cert70_text, annotate_preview
)

# ============================================================================
# SESIÓN (claves usadas para la vista previa)
# ============================================================================
SESSION_ROWS = "upload_preview_rows"      # lista de filas normalizadas
SESSION_MODE = "upload_mode"              # "montos" | "factors"
SESSION_META = "upload_meta"              # {"nombre":..., "tipo":"csv"|"pdf"}


# ============================================================================
# HELPERS LOCALES
# ============================================================================
def _clear_upload_session(request) -> None:
    """Borra las claves de sesión usadas para la carga/preview."""
    for key in (SESSION_ROWS, SESSION_MODE, SESSION_META):
        request.session.pop(key, None)

def _ext(fname: str) -> str:
    """Devuelve extensión en minúsculas, p.ej. '.csv'."""
    return os.path.splitext(fname.lower())[1]


# ============================================================================
# SUBIDA + VALIDACIÓN (CSV / PDF)
# ============================================================================
@login_required(login_url="login")
@permission_required("core.add_tblcalificacion", raise_exception=True)
def carga_archivo(request):
    """
    Sube un CSV o PDF (Cert70), valida y genera una vista previa.
    - CSV: detecta si viene por 'montos' o por 'factors' (según columnas).
    - PDF: extrae texto, parsea y normaliza filas.
    La importación real sucede en 'carga_confirmar'.
    """
    # POST con archivo: procesar
    if request.method == "POST" and request.FILES.get("archivo"):
        f = request.FILES["archivo"]
        fname = f.name
        ext = _ext(fname)

        # Solo aceptamos CSV o PDF
        if ext not in (".csv", ".pdf"):
            messages.error(request, "Sube un archivo .csv o .pdf.")
            return render(request, "calificaciones/carga_archivo.html")

        try:
            # --- CSV ---
            if ext == ".csv":
                rows, modo = parse_csv(TextIOWrapper(f, encoding="utf-8", newline=""))
                tipo_archivo = "csv"
                print(f"DEBUG CSV: {len(rows)} filas procesadas")

            # --- PDF (Certificado 70) ---
            else:
                print(f"DEBUG: Procesando PDF: {fname}")
                print(f"DEBUG: Tamaño archivo: {f.size} bytes")
                rows, modo = parse_cert70_text(f)
                tipo_archivo = "pdf"
                print(f"DEBUG PDF: {len(rows)} filas procesadas, modo: {modo}")

            # Debe haber filas válidas
            if not rows:
                print("DEBUG: No se detectaron filas válidas")
                messages.warning(request, "No se detectaron filas válidas.")
                return render(request, "calificaciones/carga_archivo.html")

            # Anota errores/advertencias y campos auxiliares para el preview
            annotate_preview(rows, modo)

            # Guardamos datos en sesión para la confirmación
            request.session[SESSION_ROWS] = rows
            request.session[SESSION_MODE] = modo
            request.session[SESSION_META] = {"nombre": fname, "tipo": tipo_archivo}
            request.session.modified = True

            # Métricas rápidas para mostrar en la vista previa
            total = len(rows)
            errores = sum(1 for r in rows if r.get("pre_error"))
            advertencias = sum(1 for r in rows if r.get("pre_warning"))
            validos = total - errores - advertencias
            can_import = (errores == 0)

            return render(request, "calificaciones/carga_archivo.html", {
                "preview_rows": rows[:5],        # solo un vistazo
                "modo_detectado": modo,          # "montos" | "factors"
                "total": total,
                "validos": validos,
                "advertencias": advertencias,
                "errores": errores,
                "can_import": can_import,        # habilita/oculta botón Importar
                "archivo_nombre": fname,
                "tipo_archivo": tipo_archivo,
                "page_title": "Carga de Calificaciones",
                "header_title": "📁 Carga de Calificaciones",
                "header_subtitle": "CSV por montos/factores o PDF (Cert70)",
            })

        except Exception as ex:
            # Cualquier error durante el parseo
            messages.error(request, f"Error al procesar archivo: {ex}")
            return render(request, "calificaciones/carga_archivo.html")

    # GET o POST sin archivo: mostrar formulario vacío
    return render(request, "calificaciones/carga_archivo.html", {
        "page_title": "Carga de Calificaciones",
        "header_title": "📁 Carga de Calificaciones",
        "header_subtitle": "CSV por montos/factores o PDF (Cert70)",
    })


# ============================================================================
# CONFIRMAR IMPORTACIÓN (persiste datos en BD)
# ============================================================================
@login_required(login_url="login")
@permission_required("core.add_tblcalificacion", raise_exception=True)
def carga_confirmar(request):
    """
    Importa definitivamente las filas de la vista previa (desde sesión).
    Reglas:
      - CSV + modo 'montos': calcula factores (base = suma posiciones 8..19).
      - CSV + modo 'factors' y PDF: persiste factores tal cual (valida suma 8..19 <= 1).
    """
    # Solo se permite via POST (botón "Importar")
    if request.method != "POST":
        return redirect("carga_archivo")

    rows = request.session.get(SESSION_ROWS) or []
    modo = request.session.get(SESSION_MODE) or "montos"
    meta = request.session.get(SESSION_META) or {}

    print(f"\nDEBUG CONFIRMAR: Total filas en sesión: {len(rows)}")
    print(f"DEBUG CONFIRMAR: Modo detectado: {modo}")
    print(f"DEBUG CONFIRMAR: Meta: {meta}")
    if rows:
        print(f"DEBUG CONFIRMAR: Primera fila keys: {list(rows[0].keys())}")
        print(f"DEBUG CONFIRMAR: Primera fila data: {rows[0]}")

    # Debe existir preview en sesión
    if not rows:
        messages.error(request, "No hay vista previa en sesión.")
        return redirect("carga_archivo")

    # Servidor bloquea si quedaron errores en la validación previa
    if any(r.get("pre_error") for r in rows):
        messages.error(request, "No se puede importar: existen registros con errores en la validación.")
        return redirect("carga_archivo")

    # Creamos registro de archivo fuente (para trazabilidad). Si falla, continuamos sin romper.
    try:
        archivo_fuente = TblArchivoFuente.objects.create(
            nombre_archivo=meta.get("nombre", "upload"),
            ruta_almacenamiento=f"calificaciones/{meta.get('nombre','upload')}",
            usuario=request.user,
        )
    except Exception:
        archivo_fuente = None  # fallback

    def_map = _build_def_map()   # Catálogo {pos: TblFactorDef}
    created = updated = skipped = 0
    errores: list[str] = []

    # Transacción: todo o nada por consistencia
    with transaction.atomic():
        for i, r in enumerate(rows, start=1):
            try:
                print(f"\nDEBUG: Procesando fila {i}")
                print(f"DEBUG: Keys en fila: {[k for k in r.keys() if 'MONTO' in k or 'FACTOR' in k]}")
                # ----------------- Encabezado/calificación base -----------------
                ejercicio   = to_int(r.get("ejercicio"))
                sec_eve     = to_int(r.get("sec_eve"))
                fec_pago    = r.get("fecha_pago") or None
                nemo        = r.get("nemo") or r.get("instrumento") or ((meta.get("tipo") == "pdf") and "PDF") or ""
                descripcion = r.get("descripcion") or ((meta.get("tipo") == "pdf") and "PDF Cert70") or ""
                mercado     = find_mercado(r.get("mercado_cod") or r.get("mercado"))
                tipo_ingreso = tipo_ingreso_by_id(r.get("tipo_ingreso_id")) \
                               or TblTipoIngreso.objects.order_by("pk").first()

                # Requisito mínimo: mercado válido
                if not mercado:
                    skipped += 1
                    errores.append(f"Fila {i}: mercado no encontrado ({r.get('mercado_cod')}).")
                    continue

                # Crea/actualiza la calificación principal (clave: ejercicio + secuencia_evento)
                calif, was_created = TblCalificacion.objects.get_or_create(
                    ejercicio=ejercicio,
                    secuencia_evento=sec_eve,
                    defaults={
                        "mercado": mercado,
                        "instrumento_text": nemo,
                        "tipo_ingreso": tipo_ingreso,
                        "descripcion": descripcion,
                        "fecha_pago_dividendo": fec_pago,
                        "dividendo": to_dec(r.get("dividendo")),  # Col 1: número del dividendo
                        "factor_actualizacion": to_dec(r.get("factor_actualizacion"), D("1")),  # Col 5
                        "usuario": request.user,
                        "archivo_fuente": archivo_fuente,
                    }
                )

                # Si ya existía: refresca campos básicos
                if not was_created:
                    calif.mercado = mercado
                    calif.instrumento_text = nemo
                    calif.tipo_ingreso = tipo_ingreso
                    calif.descripcion = descripcion
                    if fec_pago:
                        calif.fecha_pago_dividendo = fec_pago
                    calif.usuario = request.user
                    if archivo_fuente:
                        calif.archivo_fuente = archivo_fuente
                    calif.save(update_fields=[
                        "mercado", "instrumento_text", "tipo_ingreso", "descripcion",
                        "fecha_pago_dividendo", "usuario", "archivo_fuente"
                    ])

                # ----------------- Persistencia de factores -----------------
                print(f"DEBUG: Entrando a persistencia - modo={modo}, tipo={meta.get('tipo')}")
                # CSV + 'montos' -> calcula factores proporcionalmente a total (8..19)
                if modo == "montos":  # Aplica tanto para CSV como para PDF
                    total_base = D("0")
                    montos: dict[int, D] = {}

                    # Recolecta montos por posición
                    for k, v in r.items():
                        pos = is_monto_col(k)
                        if pos:
                            m = to_dec(v)
                            montos[pos] = m
                            if POS_MIN <= pos <= POS_BASE_MAX:
                                total_base += m

                    # Necesitamos total > 0 para poder calcular
                    if total_base <= 0:
                        skipped += 1
                        errores.append(f"Fila {i}: total 8..19 = 0; no se pueden calcular factores.")
                        continue

                    # Calcula y guarda
                    for pos in range(POS_MIN, POS_MAX + 1):
                        m = montos.get(pos, D("0"))
                        factor = _round8(m / total_base) if total_base > 0 else D("0")
                        TblFactorValor.objects.update_or_create(
                            calificacion=calif,
                            posicion=pos,
                            defaults={
                                "monto_base": m,
                                "valor": factor,
                                "factor_def": def_map.get(pos),
                            },
                        )

                # CSV (modo 'factors') o PDF con factores directos -> valida suma 8..19 <= 1 y guarda tal cual
                else:
                    suma_8_19 = D("0")
                    factores: dict[int, D] = {}

                    # Recolecta factores por posición
                    for k, v in r.items():
                        p = is_factor_col(k)
                        if p:
                            fval = to_dec(v)
                            factores[p] = fval
                            if POS_MIN <= p <= POS_BASE_MAX:
                                suma_8_19 += fval

                    # Suma de base no puede superar 1.0
                    if suma_8_19 > D("1"):
                        skipped += 1
                        errores.append(f"Fila {i}: suma 8..19 = {suma_8_19} > 1.0")
                        continue

                    # Guarda factores tal cual
                    for pos in range(POS_MIN, POS_MAX + 1):
                        fval = factores.get(pos, D("0"))
                        TblFactorValor.objects.update_or_create(
                            calificacion=calif,
                            posicion=pos,
                            defaults={
                                "monto_base": None,
                                "valor": fval,
                                "factor_def": def_map.get(pos),
                            },
                        )

                # Contabiliza resultado (creado vs actualizado)
                if was_created:
                    created += 1
                else:
                    updated += 1

            except Exception as ex:
                # Cualquier problema en la fila -> se omite y se reporta
                skipped += 1
                errores.append(f"Fila {i}: {ex}")

    # Limpia sesión de preview para evitar re-importes accidentales
    _clear_upload_session(request)

    # Mensajes finales
    if errores:
        # Muestra solo los primeros N errores para no saturar
        messages.warning(request, "Algunas filas se omitieron:\n" + "\n".join(errores[:10]))
    messages.success(
        request,
        f"Grabado OK. Creados: {created}, Actualizados: {updated}, Omitidos: {skipped}."
    )
    return redirect("main")
