from __future__ import annotations
import pdfplumber
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.db import transaction
from django.shortcuts import render, redirect

from core.models import TblCalificacion, TblFactorValor, TblArchivoFuente, TblTipoIngreso
from core.views import _build_def_map, POS_MIN, POS_BASE_MAX, POS_MAX
from core.ingestion_helpers import (
    to_int, to_dec, find_mercado, tipo_ingreso_by_id,
    parse_cert70_text, is_factor_col, annotate_preview
)

PDF_SESSION_ROWS = "pdf_preview_rows"
PDF_SESSION_MODE = "pdf_mode"
PDF_SESSION_META = "pdf_meta"

@login_required(login_url="login")
@permission_required("core.add_tblcalificacion", raise_exception=True)
def pdf_upload(request):
    if request.method == "POST" and request.FILES.get("archivo"):
        f = request.FILES["archivo"]
        if not f.name.lower().endswith(".pdf"):
            messages.error(request, "Sube un archivo .pdf")
            return render(request, "sandbox/carga_pdf.html")

        try:
            txt = ""
            with pdfplumber.open(f) as pdf:
                for page in pdf.pages:
                    txt += "\n" + (page.extract_text() or "")

            rows, modo = parse_cert70_text(txt)
            annotate_preview(rows, modo)

            request.session[PDF_SESSION_ROWS] = rows
            request.session[PDF_SESSION_MODE] = modo
            request.session[PDF_SESSION_META] = {"nombre": f.name}
            request.session.modified = True

            total = len(rows)
            warnings = sum(1 for r in rows if r.get("pre_warning"))
            errors   = sum(1 for r in rows if r.get("pre_error"))
            validos  = total - warnings - errors

            return render(request, "sandbox/carga_pdf.html", {
                "preview_rows": rows[:5],
                "modo_detectado": modo,
                "total": total, "validos": validos, "advertencias": warnings, "errores": errors,
            })
        except Exception as ex:
            messages.error(request, f"Error al procesar PDF: {ex}")
            return render(request, "sandbox/carga_pdf.html")

    return render(request, "sandbox/carga_pdf.html")


@login_required(login_url="login")
@permission_required("core.add_tblcalificacion", raise_exception=True)
def pdf_confirm(request):
    if request.method != "POST":
        return redirect("pdf_carga")

    rows = request.session.get(PDF_SESSION_ROWS) or []
    meta = request.session.get(PDF_SESSION_META) or {}
    if not rows:
        messages.error(request, "No hay vista previa en sesión.")
        return redirect("pdf_carga")

    try:
        archivo_fuente = TblArchivoFuente.objects.create(
            nombre_archivo=meta.get("nombre", "pdf_sandbox"),
            ruta_almacenamiento=f"sandbox/{meta.get('nombre','pdf')}",
            usuario=request.user,
        )
    except Exception:
        archivo_fuente = None

    created = updated = skipped = 0
    errores: list[str] = []

    with transaction.atomic():
        for i, r in enumerate(rows, start=1):
            try:
                ejercicio = to_int(r.get("ejercicio"))
                sec_eve   = to_int(r.get("sec_eve"))
                fec_pago  = r.get("fecha_pago") or None
                nemo      = r.get("nemo") or "PDF"
                descripcion = r.get("descripcion") or "PDF Cert70"
                mercado = find_mercado(r.get("mercado_cod") or r.get("mercado"))
                tipo_ingreso = tipo_ingreso_by_id(r.get("tipo_ingreso_id")) \
                               or TblTipoIngreso.objects.order_by("pk").first()

                if not mercado:
                    skipped += 1
                    errores.append(f"Fila {i}: mercado no encontrado.")
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

                # PDF = factores
                from decimal import Decimal as D
                suma_8_19 = D("0"); factores = {}
                for k, v in r.items():
                    p = is_factor_col(k)
                    if p:
                        fval = to_dec(v); factores[p] = fval
                        if POS_MIN <= p <= POS_BASE_MAX:
                            suma_8_19 += fval

                if suma_8_19 > Decimal("1"):
                    skipped += 1
                    errores.append(f"Fila {i}: suma 8..19 = {suma_8_19} > 1.0")
                    continue

                for pos in range(POS_MIN, POS_MAX + 1):
                    fval = factores.get(pos, Decimal("0"))
                    TblFactorValor.objects.update_or_create(
                        calificacion=calif, posicion=pos,
                        defaults={"monto_base": None, "valor": fval}
                    )

                if was_created: created += 1
                else: updated += 1

            except Exception as ex:
                skipped += 1
                errores.append(f"Fila {i}: {ex}")

    for key in (PDF_SESSION_ROWS, PDF_SESSION_MODE, PDF_SESSION_META):
        request.session.pop(key, None)

    if errores:
        messages.warning(request, "Algunas filas se omitieron:\n" + "\n".join(errores[:10]))
    messages.success(request, f"Grabado PDF OK. Creados: {created}, Actualizados: {updated}, Omitidos: {skipped}.")
    return redirect("main")
