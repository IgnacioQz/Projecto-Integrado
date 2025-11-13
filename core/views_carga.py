from __future__ import annotations
import os
from io import TextIOWrapper
from decimal import Decimal as D

import pdfplumber
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.db import transaction
from django.shortcuts import render, redirect

from core.models import TblCalificacion, TblFactorValor, TblArchivoFuente, TblTipoIngreso
from core.views import _round8, _build_def_map, POS_MIN, POS_BASE_MAX, POS_MAX
from core.ingestion_helpers import (
    to_int, to_dec, is_monto_col, is_factor_col,
    find_mercado, tipo_ingreso_by_id,
    parse_csv, parse_cert70_text, annotate_preview
)

# Sesión unificada
SESSION_ROWS = "upload_preview_rows"
SESSION_MODE = "upload_mode"        # "montos" | "factors" (según tu parser)
SESSION_META = "upload_meta"        # {"nombre":..., "tipo":"csv"|"pdf"}

@login_required(login_url="login")
@permission_required("core.add_tblcalificacion", raise_exception=True)
def carga_archivo(request):
    """
    Subida + validación para CSV y PDF (unificada).
    """
    if request.method == "POST" and request.FILES.get("archivo"):
        f = request.FILES["archivo"]
        fname = f.name
        ext = os.path.splitext(fname.lower())[1]

        if ext not in (".csv", ".pdf"):
            messages.error(request, "Sube un archivo .csv o .pdf")
            return render(request, "calificaciones/carga_archivo.html")

        try:
            if ext == ".csv":
                rows, modo = parse_csv(TextIOWrapper(f, encoding="utf-8", newline=""))
                tipo_archivo = "csv"
            else:
                # PDF
                with pdfplumber.open(f) as pdf:
                    txt = "\n".join((page.extract_text() or "") for page in pdf.pages)
                rows, modo = parse_cert70_text(txt)
                tipo_archivo = "pdf"

            if not rows:
                messages.warning(request, "No se detectaron filas válidas.")
                return render(request, "calificaciones/carga_archivo.html")

            # anota warnings/errores + agregados de preview
            annotate_preview(rows, modo)

            # guardar en sesión
            request.session[SESSION_ROWS] = rows
            request.session[SESSION_MODE] = modo
            request.session[SESSION_META] = {"nombre": fname, "tipo": tipo_archivo}
            request.session.modified = True

            total = len(rows)
            errores = sum(1 for r in rows if r.get("pre_error"))
            advertencias = sum(1 for r in rows if r.get("pre_warning"))
            validos = total - errores - advertencias
            can_import = (errores == 0)

            return render(request, "calificaciones/carga_archivo.html", {
                "preview_rows": rows[:5],
                "modo_detectado": modo,
                "total": total,
                "validos": validos,
                "advertencias": advertencias,
                "errores": errores,
                "can_import": can_import,
                "archivo_nombre": fname,
                "tipo_archivo": tipo_archivo,
                "page_title": "Carga de Calificaciones",
                "header_title": "📁 Carga de Calificaciones",
                "header_subtitle": "CSV por montos/factores o PDF (Cert70)",
            })

        except Exception as ex:
            messages.error(request, f"Error al procesar archivo: {ex}")
            return render(request, "calificaciones/carga_archivo.html")

    # GET o primera carga sin archivo
    return render(request, "calificaciones/carga_archivo.html", {
        "page_title": "Carga de Calificaciones",
        "header_title": "📁 Carga de Calificaciones",
        "header_subtitle": "CSV por montos/factores o PDF (Cert70)",
    })


@login_required(login_url="login")
@permission_required("core.add_tblcalificacion", raise_exception=True)
def carga_confirmar(request):
    """
    Importa definitivamente lo que está en la vista previa (CSV o PDF).
    En CSV: si modo == "montos" calcula factores (8..19 como base).
    En CSV (modo factores) y PDF: persiste factores tal cual, validando suma 8..19 <= 1.
    """
    if request.method != "POST":
        return redirect("carga_archivo")

    rows = request.session.get(SESSION_ROWS) or []
    modo = request.session.get(SESSION_MODE) or "montos"
    meta = request.session.get(SESSION_META) or {}

    if not rows:
        messages.error(request, "No hay vista previa en sesión.")
        return redirect("carga_archivo")

    # Bloqueo server-side si hay errores
    if any(r.get("pre_error") for r in rows):
        messages.error(request, "No se puede importar: existen registros con errores en la validación.")
        return redirect("carga_archivo")

    # crear archivo_fuente
    try:
        archivo_fuente = TblArchivoFuente.objects.create(
            nombre_archivo = meta.get("nombre", "upload"),
            ruta_almacenamiento = f"calificaciones/{meta.get('nombre','upload')}", 
            usuario = request.user,
        )
    except Exception:
        archivo_fuente = None

    def_map = _build_def_map()
    created = updated = skipped = 0
    errores: list[str] = []

    with transaction.atomic():
        for i, r in enumerate(rows, start=1):
            try:
                ejercicio = to_int(r.get("ejercicio"))
                sec_eve   = to_int(r.get("sec_eve"))
                fec_pago  = r.get("fecha_pago") or None
                nemo      = r.get("nemo") or r.get("instrumento") or (meta.get("tipo") == "pdf" and "PDF") or ""
                descripcion = r.get("descripcion") or ((meta.get("tipo") == "pdf") and "PDF Cert70") or ""
                mercado = find_mercado(r.get("mercado_cod") or r.get("mercado"))
                tipo_ingreso = tipo_ingreso_by_id(r.get("tipo_ingreso_id")) \
                               or TblTipoIngreso.objects.order_by("pk").first()

                if not mercado:
                    skipped += 1
                    errores.append(f"Fila {i}: mercado no encontrado ({r.get('mercado_cod')}).")
                    continue

                calif, was_created = TblCalificacion.objects.get_or_create(
                    ejercicio=ejercicio, secuencia_evento=sec_eve,
                    defaults={
                        "mercado": mercado,
                        "instrumento_text": nemo,
                        "tipo_ingreso": tipo_ingreso,
                        "descripcion": descripcion,
                        "fecha_pago_dividendo": fec_pago,
                        "usuario": request.user,
                        "archivo_fuente": archivo_fuente,
                    }
                )

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
                        "mercado","instrumento_text","tipo_ingreso","descripcion",
                        "fecha_pago_dividendo","usuario","archivo_fuente"
                    ])

                # ---- Persistencia de factores según origen/modo ----
                if meta.get("tipo") == "csv" and modo == "montos":
                    total_base = D("0"); montos = {}
                    for k, v in r.items():
                        pos = is_monto_col(k)
                        if pos:
                            m = to_dec(v); montos[pos] = m
                            if POS_MIN <= pos <= POS_BASE_MAX:
                                total_base += m

                    if total_base <= 0:
                        skipped += 1
                        errores.append(f"Fila {i}: total 8..19 = 0; no se pueden calcular factores.")
                        continue

                    for pos in range(POS_MIN, POS_MAX + 1):
                        m = montos.get(pos, D("0"))
                        factor = _round8(m / total_base) if total_base > 0 else D("0")
                        factor_def = def_map.get(pos)
                        TblFactorValor.objects.update_or_create(
                            calificacion=calif, posicion=pos,
                            defaults={
                                "monto_base": m,
                                "valor": factor,
                                "factor_def": factor_def,
                                }
                        )

                else:
                    # CSV (modo factores) o PDF: validar suma 8..19 <= 1 y grabar
                    suma_8_19 = D("0"); factores = {}
                    for k, v in r.items():
                        p = is_factor_col(k)
                        if p:
                            fval = to_dec(v); factores[p] = fval
                            if POS_MIN <= p <= POS_BASE_MAX:
                                suma_8_19 += fval

                    if suma_8_19 > D("1"):
                        skipped += 1
                        errores.append(f"Fila {i}: suma 8..19 = {suma_8_19} > 1.0")
                        continue

                    for pos in range(POS_MIN, POS_MAX + 1):
                        fval = factores.get(pos, D("0"))
                        factor_def = def_map.get(pos)
                        TblFactorValor.objects.update_or_create(
                            calificacion=calif, posicion=pos,
                            defaults={
                                "monto_base": None,
                                "valor": fval,
                                "factor_def": factor_def,
                                }
                        )

                if was_created: created += 1
                else: updated += 1

            except Exception as ex:
                skipped += 1
                errores.append(f"Fila {i}: {ex}")

    # limpiar sesión
    for key in (SESSION_ROWS, SESSION_MODE, SESSION_META):
        request.session.pop(key, None)

    if errores:
        messages.warning(request, "Algunas filas se omitieron:\n" + "\n".join(errores[:10]))
    messages.success(request, f"Grabado OK. Creados: {created}, Actualizados: {updated}, Omitidos: {skipped}.")
    return redirect("main")
