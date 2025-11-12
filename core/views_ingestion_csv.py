from __future__ import annotations
from decimal import Decimal
from io import TextIOWrapper

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.db import transaction
from django.shortcuts import render, redirect

from core.models import TblCalificacion, TblFactorValor, TblArchivoFuente, TblTipoIngreso
from core.views import _round8, _build_def_map, POS_MIN, POS_BASE_MAX, POS_MAX
from core.ingestion_helpers import (
    to_int, to_dec, is_monto_col, is_factor_col,
    find_mercado, tipo_ingreso_by_id, parse_csv, annotate_preview
)

CSV_SESSION_ROWS = "csv_preview_rows"
CSV_SESSION_MODE = "csv_mode"
CSV_SESSION_META = "csv_meta"


def _detalle_factores_text(d: dict[int, Decimal], modo: str) -> str:
    """
    Construye un string corto con los primeros factores/montos != 0.
    Ej: 'F8=0.80000000, F9=0.20000000'  o  'F8=$30000.00, F9=$20000.00'
    """
    pares = []
    # recorro en orden de posición 8..37
    for p in range(POS_MIN, POS_MAX + 1):
        if p in d and d[p] not in (None, Decimal("0"), Decimal("0.00000000")):
            v = d[p]
            if modo == "montos":
                pares.append(f"F{p}=${v:.2f}")
            else:
                # factores
                try:
                    pares.append(f"F{p}={Decimal(v):.8f}")
                except Exception:
                    pares.append(f"F{p}={v}")
        if len(pares) >= 6:  # no saturar
            break
    return ", ".join(pares) if pares else "(sin valores)"



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

            # anota warnings/errores + agregados de preview
            annotate_preview(rows, modo)

            # guarda en sesión
            request.session[CSV_SESSION_ROWS] = rows
            request.session[CSV_SESSION_MODE] = modo
            request.session[CSV_SESSION_META] = {"nombre": f.name}
            request.session.modified = True

            total = len(rows)
            errores = sum(1 for r in rows if r.get("pre_error"))
            advertencias = sum(1 for r in rows if r.get("pre_warning"))
            validos = total - errores - advertencias

            # 👇 clave para la template
            can_import = (errores == 0)

            return render(request, "sandbox/carga_csv.html", {
                "preview_rows": rows[:5],
                "modo_detectado": modo,
                "total": total,
                "validos": validos,
                "advertencias": advertencias,
                "errores": errores,
                "can_import": can_import,
            })
        except Exception as ex:
            messages.error(request, f"Error al procesar CSV: {ex}")
            return render(request, "sandbox/carga_csv.html")

    # GET o primera carga sin archivo
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

    # ✅ bloqueo server-side si existe cualquier error en la preview
    if any(r.get("pre_error") for r in rows):
        messages.error(request, "No se puede importar: existen registros con errores en la validación.")
        return redirect("csv_carga")

    # (opcional) si quieres recalcular por seguridad:
    # from core.ingestion_helpers import annotate_preview
    # annotate_preview(rows, modo)
    # if any(r.get("pre_error") for r in rows): ...

    # --- persistencia normal (tu lógica actual) ---
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
                        TblFactorValor.objects.update_or_create(
                            calificacion=calif, posicion=pos,
                            defaults={"monto_base": m, "valor": factor}
                        )
                else:  # factores
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
                        TblFactorValor.objects.update_or_create(
                            calificacion=calif, posicion=pos,
                            defaults={"monto_base": None, "valor": f}
                        )

                if was_created: created += 1
                else: updated += 1

            except Exception as ex:
                skipped += 1
                errores.append(f"Fila {i}: {ex}")

    # limpia sesión
    for key in (CSV_SESSION_ROWS, CSV_SESSION_MODE, CSV_SESSION_META):
        request.session.pop(key, None)

    if errores:
        messages.warning(request, "Algunas filas se omitieron:\n" + "\n".join(errores[:10]))
    messages.success(request, f"Grabado CSV OK. Creados: {created}, Actualizados: {updated}, Omitidos: {skipped}.")
    return redirect("main")