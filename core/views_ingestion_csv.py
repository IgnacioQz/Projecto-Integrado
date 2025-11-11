# core/views_ingestions_csv.py
from __future__ import annotations
from decimal import Decimal
from io import TextIOWrapper

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.db import transaction
from django.shortcuts import render, redirect

from core.models import TblCalificacion, TblFactorValor, TblArchivoFuente, TblTipoIngreso, TblFactorDef
from core.views import _round8, _build_def_map, POS_MIN, POS_BASE_MAX, POS_MAX
from core.ingestion_helpers import (
    to_int, to_dec, is_monto_col, is_factor_col,
    find_mercado, tipo_ingreso_by_id, parse_csv, annotate_preview
)

CSV_SESSION_ROWS = "csv_preview_rows"
CSV_SESSION_MODE = "csv_mode"
CSV_SESSION_META = "csv_meta"


# =============================================================================
# CARGA CSV
# =============================================================================

@login_required(login_url="login")
@permission_required("core.add_tblcalificacion", raise_exception=True)
def csv_upload(request):
    if request.method == "POST" and request.FILES.get("archivo"):
        f = request.FILES["archivo"]
        if not f.name.lower().endswith(".csv"):
            messages.error(request, "Sube un archivo .csv")
            return render(request, "sandbox/carga_csv.html")

        try:
            rows, modo = parse_csv(TextIOWrapper(f, encoding="utf-8", newline=""))
            if not rows:
                messages.warning(request, "No se detectaron filas válidas.")
                return render(request, "sandbox/carga_csv.html")

            annotate_preview(rows, modo)
            request.session[CSV_SESSION_ROWS] = rows
            request.session[CSV_SESSION_MODE] = modo
            request.session[CSV_SESSION_META] = {"nombre": f.name}
            request.session.modified = True

            total = len(rows)
            warnings = sum(1 for r in rows if r.get("pre_warning"))
            errors   = sum(1 for r in rows if r.get("pre_error"))
            validos  = total - warnings - errors

            return render(request, "sandbox/carga_csv.html", {
                "preview_rows": rows[:5],
                "modo_detectado": modo,
                "total": total, "validos": validos, "advertencias": warnings, "errores": errors,
            })
        except Exception as ex:
            messages.error(request, f"Error al procesar CSV: {ex}")
            return render(request, "sandbox/carga_csv.html")

    return render(request, "sandbox/carga_csv.html")


@login_required(login_url="login")
@permission_required("core.add_tblcalificacion", raise_exception=True)
def csv_confirm(request):
    if request.method != "POST":
        return redirect("csv_carga")

    rows = request.session.get(CSV_SESSION_ROWS) or []
    modo = request.session.get(CSV_SESSION_MODE) or "montos"
    meta = request.session.get(CSV_SESSION_META) or {}

    if not rows:
        messages.error(request, "No hay vista previa en sesión.")
        return redirect("csv_carga")

    try:
        archivo_fuente = TblArchivoFuente.objects.create(
            nombre_archivo=meta.get("nombre", "csv_sandbox"),
            ruta_almacenamiento=f"sandbox/{meta.get('nombre','csv')}",
            usuario=request.user,
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
                nemo      = r.get("nemo") or r.get("instrumento") or ""
                descripcion = r.get("descripcion") or ""
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

                # =================================================================
                #   MONTO o FACTORES
                # =================================================================
                if modo == "montos":
                    from decimal import Decimal as D
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

                else:  # modo FACTORES
                    from decimal import Decimal as D
                    suma_8_19 = D("0"); factores = {}
                    for k, v in r.items():
                        p = is_factor_col(k)
                        if p:
                            f = to_dec(v); factores[p] = f
                            if POS_MIN <= p <= POS_BASE_MAX:
                                suma_8_19 += f

                    if suma_8_19 > D("1"):
                        skipped += 1
                        errores.append(f"Fila {i}: suma factores 8..19 = {suma_8_19} > 1.0")
                        continue

                    for pos in range(POS_MIN, POS_MAX + 1):
                        f = factores.get(pos, D("0"))
                        factor_def = def_map.get(pos)
                        TblFactorValor.objects.update_or_create(
                            calificacion=calif, posicion=pos,
                            defaults={
                                "monto_base": None,
                                "valor": f,
                                "factor_def": factor_def,
                            }
                        )

                if was_created: created += 1
                else: updated += 1

            except Exception as ex:
                skipped += 1
                errores.append(f"Fila {i}: {ex}")

    # Limpieza de sesión
    for key in (CSV_SESSION_ROWS, CSV_SESSION_MODE, CSV_SESSION_META):
        request.session.pop(key, None)

    if errores:
        messages.warning(request, "Algunas filas se omitieron:\n" + "\n".join(errores[:10]))
    messages.success(request, f"Grabado CSV OK. Creados: {created}, Actualizados: {updated}, Omitidos: {skipped}.")
    return redirect("main")
