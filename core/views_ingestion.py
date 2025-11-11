# core/views_ingestion.py
from __future__ import annotations
from decimal import Decimal
import csv
import io
import re
from io import TextIOWrapper
import pdfplumber

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.db import transaction
from django.shortcuts import render, redirect
from django.utils import timezone

from core.models import (
    TblCalificacion, TblFactorValor, TblMercado, TblTipoIngreso, TblArchivoFuente
)
# Reusar helpers del mantenedor
from .views import _round8, _build_def_map, POS_MIN, POS_BASE_MAX, POS_MAX

SESSION_KEY = "sandbox_preview_rows"
SESSION_MODE = "sandbox_mode"     # "montos" | "factores"
SESSION_META = "sandbox_meta"     # info del archivo

# -------------------------------------------------
# Helpers genéricos
# -------------------------------------------------
def _to_int(v, default=0):
    try:
        return int(str(v).strip())
    except Exception:
        return default

def _to_dec(v, default=Decimal("0")):
    if v is None or v == "":
        return default
    s = str(v).strip().replace(",", ".")  # por si vienen comas decimales
    try:
        return Decimal(s)
    except Exception:
        return default

def _find_mercado(codigo_o_nombre: str) -> TblMercado | None:
    if not codigo_o_nombre:
        return None
    s = str(codigo_o_nombre).strip()
    m = TblMercado.objects.filter(codigo__iexact=s).first()
    if m: return m
    return TblMercado.objects.filter(nombre__iexact=s).first()

def _tipo_ingreso_by_id(tipo_id: str|int|None) -> TblTipoIngreso | None:
    if not tipo_id:
        return None
    try:
        return TblTipoIngreso.objects.get(pk=int(tipo_id))
    except Exception:
        return None

def _is_factor_col(header: str) -> int|None:
    h = header.strip().upper()
    if h.startswith("F") and h.endswith("_FACTOR"):
        try:
            pos = int(h[1:h.index("_")])
            return pos if POS_MIN <= pos <= POS_MAX else None
        except Exception:
            return None
    return None

def _is_monto_col(header: str) -> int|None:
    h = header.strip().upper()
    if h.startswith("F") and h.endswith("_MONTO"):
        try:
            pos = int(h[1:h.index("_")])
            return pos if POS_MIN <= pos <= POS_MAX else None
        except Exception:
            return None
    return None

# -------------------------------------------------
# SANDBOX: Upload / Preview
# -------------------------------------------------
@login_required(login_url="login")
@permission_required("core.add_tblcalificacion", raise_exception=True)
def sandbox_upload(request):
    """
    GET -> muestra formulario
    POST -> lee CSV/PDF, arma preview y guarda en session
    """
    if request.method == "POST" and request.FILES.get("archivo"):
        f = request.FILES["archivo"]
        nombre = (f.name or "").lower()

        try:
            if nombre.endswith(".csv"):
                # Usar directamente el UploadedFile (no f.file) y detectar delimitador.
                rows, modo = _parse_csv(TextIOWrapper(f, encoding="utf-8", newline=""))
            elif nombre.endswith(".pdf"):
                rows, modo = _parse_cert70_pdf(f)
            else:
                messages.error(request, "Formato no soportado. Use .csv o .pdf")
                return render(request, "sandbox/carga.html")

            if not rows:
                messages.warning(request, "No se detectaron filas válidas en el archivo.")
                return render(request, "sandbox/carga.html")

            # Enriquecer preview con status y métricas
            _annotate_preview(rows)

            # Guardar en sesión (valores simples/serializables)
            request.session[SESSION_KEY] = rows
            request.session[SESSION_MODE] = modo
            request.session[SESSION_META] = {"nombre": f.name, "ts": timezone.now().isoformat()}
            request.session.modified = True

            total = len(rows)
            nuevos = sum(1 for r in rows if r.get("status") == "nuevo")
            actualiza = total - nuevos

            messages.info(request, f"Vista previa generada. Modo detectado: {modo}.")
            return render(request, "sandbox/carga.html", {
                "preview_rows": rows,
                "modo_detectado": modo,
                "total": total, "nuevos": nuevos, "actualiza": actualiza,
            })
        except Exception as ex:
            messages.error(request, f"Error al procesar archivo: {ex}")
            return render(request, "sandbox/carga.html")

    # GET
    return render(request, "sandbox/carga.html")

# -------------------------------------------------
# SANDBOX: Confirmar / Grabar
# -------------------------------------------------
@login_required(login_url="login")
@permission_required("core.add_tblcalificacion", raise_exception=True)
def sandbox_confirm(request):
    if request.method != "POST":
        return redirect("sandbox_carga")

    rows = request.session.get(SESSION_KEY) or []
    modo = request.session.get(SESSION_MODE) or "montos"
    meta = request.session.get(SESSION_META) or {}

    if not rows:
        messages.error(request, "No hay vista previa en sesión. Vuelve a subir el archivo.")
        return redirect("sandbox_carga")

    archivo_fuente = None
    try:
        archivo_fuente = TblArchivoFuente.objects.create(
            nombre_archivo=meta.get("nombre", "archivo_sandbox"),
            ruta_almacenamiento=f"sandbox/{meta.get('nombre','archivo')}",
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
                ejercicio = _to_int(r.get("ejercicio"))
                sec_eve   = _to_int(r.get("sec_eve"))
                fec_pago  = r.get("fecha_pago") or None
                nemo      = r.get("nemo") or r.get("instrumento") or ""
                descripcion = r.get("descripcion") or ""
                mercado = _find_mercado(r.get("mercado_cod") or r.get("mercado"))
                tipo_ingreso = _tipo_ingreso_by_id(r.get("tipo_ingreso_id")) or TblTipoIngreso.objects.order_by("pk").first()

                if not mercado:
                    skipped += 1
                    errores.append(f"Fila {i}: mercado no encontrado ({r.get('mercado_cod')}).")
                    continue

                calif, was_created = TblCalificacion.objects.get_or_create(
                    ejercicio=ejercicio,
                    secuencia_evento=sec_eve,
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
                    calif.archivo_fuente = archivo_fuente or calif.archivo_fuente
                    calif.save(update_fields=[
                        "mercado","instrumento_text","tipo_ingreso","descripcion",
                        "fecha_pago_dividendo","usuario","archivo_fuente"
                    ])

                if modo == "montos":
                    total_base = Decimal("0")
                    montos = {}
                    for k, v in r.items():
                        pos = _is_monto_col(k)
                        if pos:
                            m = _to_dec(v)
                            montos[pos] = m
                            if POS_MIN <= pos <= POS_BASE_MAX:
                                total_base += m

                    if total_base <= 0:
                        skipped += 1
                        errores.append(f"Fila {i}: total de montos 8..19 = 0 (no se pueden calcular factores).")
                        continue

                    for pos in range(POS_MIN, POS_MAX + 1):
                        m = montos.get(pos, Decimal("0"))
                        factor = _round8(m / total_base) if total_base > 0 else Decimal("0")
                        TblFactorValor.objects.update_or_create(
                            calificacion=calif, posicion=pos,
                            defaults={"monto_base": m, "valor": factor, "factor_def": def_map.get(pos)}
                        )
                else:  # factores directos
                    suma_8_19 = Decimal("0")
                    factores = {}
                    for k, v in r.items():
                        pos = _is_factor_col(k)
                        if pos:
                            f = _to_dec(v)
                            factores[pos] = f
                            if POS_MIN <= pos <= POS_BASE_MAX:
                                suma_8_19 += f

                    if suma_8_19 > Decimal("1"):
                        skipped += 1
                        errores.append(f"Fila {i}: suma de factores 8..19 = {suma_8_19} > 1.0")
                        continue

                    for pos in range(POS_MIN, POS_MAX + 1):
                        f = factores.get(pos, Decimal("0"))
                        TblFactorValor.objects.update_or_create(
                            calificacion=calif, posicion=pos,
                            defaults={"monto_base": None, "valor": f, "factor_def": def_map.get(pos)}
                        )

                created += 1 if was_created else 0
                updated += 0 if was_created else 1

            except Exception as ex:
                skipped += 1
                errores.append(f"Fila {i}: {ex}")

    for key in (SESSION_KEY, SESSION_MODE, SESSION_META):
        request.session.pop(key, None)

    if errores:
        messages.warning(request, "Algunas filas se omitieron:\n" + "\n".join(errores[:10]))
    messages.success(request, f"Grabado OK. Creados: {created}, Actualizados: {updated}, Omitidos: {skipped}.")
    return redirect("main")

# -------------------------------------------------
# Parsers
# -------------------------------------------------
def _normalize_headers(headers: list[str]) -> list[str]:
    """Limpia BOM y espacios; devuelve headers como los leemos del CSV."""
    if not headers:
        return []
    # El primer header podría venir con BOM
    h0 = headers[0].lstrip("\ufeff") if headers else ""
    return [h0] + [h.strip() for h in headers[1:]]

def _lookup(d: dict, *names):
    """Obtiene d[key] con llaves alternativas (case-insensitive)."""
    lower = {k.lower(): v for k, v in d.items()}
    for name in names:
        v = lower.get(name.lower())
        if v not in (None, ""):
            return v
    return ""

def _parse_csv(io_text: TextIOWrapper) -> tuple[list[dict], str]:
    """
    CSV robusto:
      - Detecta delimitador (coma, punto y coma, tab)
      - Limpia BOM en el primer header
      - Case-insensitive en nombres de columnas
    Devuelve (rows, modo) donde modo in {'montos','factores'}.
    """
    # Leer una muestra para sniffing sin perder el stream
    sample = io_text.read(4096)
    io_text.seek(0)
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=[',',';','\t'])
    except Exception:
        dialect = csv.excel  # por defecto coma

    reader = csv.DictReader(io_text, dialect=dialect)
    headers_raw = reader.fieldnames or []
    headers = _normalize_headers([h.strip() for h in headers_raw])

    # DictReader ya creó su propio mapeo; reinyectamos headers limpios
    reader.fieldnames = headers

    has_montos = any(_is_monto_col(h) for h in headers)
    has_fact   = any(_is_factor_col(h) for h in headers)
    modo = "montos" if (has_montos and not has_fact) else "factores" if has_fact else "montos"

    rows: list[dict] = []
    for row in reader:
        # row keys ya están normalizados
        r = {
            "ejercicio": _lookup(row, "EJERCICIO", "ejercicio"),
            "mercado_cod": _lookup(row, "MERCADO_COD", "mercado", "codigo_mercado"),
            "nemo": _lookup(row, "NEMO", "instrumento"),
            "fecha_pago": _lookup(row, "FEC_PAGO", "fecha_pago"),
            "sec_eve": _lookup(row, "SEC_EVE", "secuencia_evento"),
            "descripcion": _lookup(row, "DESCRIPCION"),
            "tipo_ingreso_id": _lookup(row, "TIPO_INGRESO_ID"),
        }
        # Copiar todas las columnas F* (montos o factores)
        for h in headers:
            if _is_monto_col(h) or _is_factor_col(h):
                r[h] = row.get(h, "")
        rows.append(r)
    return rows, modo

def _parse_cert70_pdf(uploaded_file) -> tuple[list[dict], str]:
    """
    Parser mínimo de ejemplo para PDF Cert70.
    """
    rows = []
    with pdfplumber.open(uploaded_file) as pdf:
        txt = ""
        for page in pdf.pages:
            t = page.extract_text() or ""
            txt += "\n" + t

    def grab(label):
        m = re.search(rf"{label}\s*:\s*([0-9\-]+)", txt, flags=re.I)
        return m.group(1) if m else ""

    r = {
        "ejercicio": grab("Ejercicio"),
        "mercado_cod": "ACC",
        "nemo": "PDF-EJEMPLO",
        "fecha_pago": grab("Fecha de pago"),
        "sec_eve": grab("Sec Eve"),
        "descripcion": "Desde PDF Cert70",
        "tipo_ingreso_id": "2",
        "F8_FACTOR": "0.80",
        "F9_FACTOR": "0.20",
        "F10_FACTOR": "0.00",
    }
    rows.append(r)
    return rows, "factores"

def _annotate_preview(rows: list[dict]) -> None:
    """Marca cada fila como 'nuevo' o 'actualiza' y agrega métricas (serializables)."""
    for r in rows:
        try:
            ej = _to_int(r.get("ejercicio"))
            se = _to_int(r.get("sec_eve"))
            exists = TblCalificacion.objects.filter(ejercicio=ej, secuencia_evento=se).exists()
            r["status"] = "actualiza" if exists else "nuevo"

            factores_con_valor = 0
            suma_8_19 = Decimal("0")
            for k, v in r.items():
                pos = _is_factor_col(k)
                if pos:
                    val = _to_dec(v)
                    if val != 0:
                        factores_con_valor += 1
                    if POS_MIN <= pos <= POS_BASE_MAX:
                        suma_8_19 += val

            r["factores_con_valor"] = factores_con_valor
            # Guardar como string para que Session JSON no falle con Decimal
            r["suma_8_19"] = str(suma_8_19)
        except Exception:
            r["status"] = "nuevo"
            r["factores_con_valor"] = 0
            r["suma_8_19"] = "0"
