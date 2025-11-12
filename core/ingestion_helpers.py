# core/ingestion_helpers.py
from __future__ import annotations
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime
import csv, re
from io import TextIOWrapper
import pdfplumber
from decimal import Decimal

from django.utils import timezone

from core.models import TblCalificacion, TblTipoIngreso, TblMercado, TblFactorDef

# Reutiliza las constantes del dominio desde views.py
from core.views import POS_MIN, POS_BASE_MAX, POS_MAX

# -----------------------------
# utils
# -----------------------------
def to_int(v, default=0):
    try:
        return int(str(v).strip())
    except Exception:
        return default

def to_dec(v, default=Decimal("0")):
    if v is None or v == "":
        return default
    s = str(v).strip().replace(",", ".")
    try:
        return Decimal(s)
    except Exception:
        return default

def _round8(x: Decimal) -> Decimal:
    return (x or Decimal("0")).quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP)

def normalize_headers(headers: list[str]) -> list[str]:
    if not headers:
        return []
    h0 = headers[0].lstrip("\ufeff")
    return [h0] + [h.strip() for h in headers[1:]]

def is_factor_col(h: str) -> int|None:
    H = (h or "").strip().upper()
    if H.startswith("F") and H.endswith("_FACTOR"):
        try:
            pos = int(H[1:H.index("_")])
            return pos if POS_MIN <= pos <= POS_MAX else None
        except Exception:
            return None
    return None

def is_monto_col(h: str) -> int|None:
    H = (h or "").strip().upper()
    if H.startswith("F") and H.endswith("_MONTO"):
        try:
            pos = int(H[1:H.index("_")])
            return pos if POS_MIN <= pos <= POS_MAX else None
        except Exception:
            return None
    return None

def lookup_ci(d: dict, *names):
    lower = {(k or "").lower(): v for k, v in d.items()}
    for name in names:
        v = lower.get((name or "").lower())
        if v not in (None, ""):
            return v
    return ""

def find_mercado(codigo_o_nombre: str):
    if not codigo_o_nombre:
        return None
    s = str(codigo_o_nombre).strip()
    m = TblMercado.objects.filter(codigo__iexact=s).first()
    if m:
        return m
    return TblMercado.objects.filter(nombre__iexact=s).first()

def tipo_ingreso_by_id(tipo_id: str|int|None):
    if not tipo_id:
        return None
    try:
        return TblTipoIngreso.objects.get(pk=int(tipo_id))
    except Exception:
        return None

def _factor_names_map() -> dict[int, str]:
    """
    Mapa {posicion:int -> 'F8 NombreFactor'} para adornar la preview.
    Si no existe en catálogo, usa solo 'F{pos}'.
    """
    out = {}
    for d in TblFactorDef.objects.filter(posicion__gte=POS_MIN, posicion__lte=POS_MAX, activo=True):
        out[int(d.posicion)] = f"F{int(d.posicion)} {d.nombre}"
    return out

# -----------------------------
# CSV
# -----------------------------
def parse_csv(io_text: TextIOWrapper):
    sample = io_text.read(4096); io_text.seek(0)
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=[",",";","\t"])
    except Exception:
        dialect = csv.excel

    reader = csv.DictReader(io_text, dialect=dialect)
    headers_raw = reader.fieldnames or []
    headers = normalize_headers([h.strip() for h in headers_raw])
    reader.fieldnames = headers

    has_montos = any(is_monto_col(h) for h in headers)
    has_fact   = any(is_factor_col(h) for h in headers)
    modo = "montos" if (has_montos and not has_fact) else "factores" if has_fact else "montos"

    rows = []
    for row in reader:
        r = {
            "ejercicio":       lookup_ci(row, "EJERCICIO", "ejercicio"),
            "mercado_cod":     lookup_ci(row, "MERCADO_COD", "mercado", "codigo_mercado"),
            "nemo":            lookup_ci(row, "NEMO", "instrumento"),
            "fecha_pago":      lookup_ci(row, "FEC_PAGO", "fecha_pago"),
            "sec_eve":         lookup_ci(row, "SEC_EVE", "secuencia_evento"),
            "descripcion":     lookup_ci(row, "DESCRIPCION"),
            "tipo_ingreso_id": lookup_ci(row, "TIPO_INGRESO_ID"),
        }
        for h in headers:
            if is_monto_col(h) or is_factor_col(h):
                r[h] = row.get(h, "")
        rows.append(r)
    return rows, modo

# -----------------------------
# PDF Cert70 (texto plano) — placeholder mínimo
# -----------------------------
def parse_cert70_text(path_pdf: str):
    rows = []
    with pdfplumber.open(path_pdf) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables()
            for tbl in tables:
                # Buscar tablas que contengan la columna 8
                header_line = [c.strip() if c else "" for c in tbl[0]]
                if any("Monto" in h or "Dividen" in h for h in header_line):
                    for row in tbl[1:]:
                        c = [str(x).strip().replace(".", "").replace(",", ".") for x in row]
                        if not c or not c[0] or "Total" in c[0]:
                            continue
                        # Ejemplo: fila con 20+ columnas (8 a 19)
                        try:
                            fecha = c[0]
                            div_nro = c[1]
                            f8  = Decimal(c[8])  if c[8]  not in ("", "0") else Decimal("0")
                            f9  = Decimal(c[9])  if c[9]  not in ("", "0") else Decimal("0")
                            f10 = Decimal(c[10]) if c[10] not in ("", "0") else Decimal("0")
                            f11 = Decimal(c[11]) if c[11] not in ("", "0") else Decimal("0")
                            f12 = Decimal(c[12]) if c[12] not in ("", "0") else Decimal("0")
                            f13 = Decimal(c[13]) if c[13] not in ("", "0") else Decimal("0")
                            f14 = Decimal(c[14]) if c[14] not in ("", "0") else Decimal("0")
                            f15 = Decimal(c[15]) if c[15] not in ("", "0") else Decimal("0")
                            f16 = Decimal(c[16]) if c[16] not in ("", "0") else Decimal("0")
                            f17 = Decimal(c[17]) if c[17] not in ("", "0") else Decimal("0")
                            f18 = Decimal(c[18]) if c[18] not in ("", "0") else Decimal("0")
                            f19 = Decimal(c[19]) if c[19] not in ("", "0") else Decimal("0")
                            suma_819 = f8 + f9 + f10 + f11 + f12 + f13 + f14 + f15 + f16 + f17 + f18 + f19

                            rows.append({
                                "ejercicio": "2021",
                                "mercado_cod": "ACC",
                                "nemo": "CAP",
                                "fecha_pago": fecha,
                                "sec_eve": div_nro,
                                "descripcion": f"Cert70 PDF: {fecha} — suma8_19={suma_819}",
                                "tipo_ingreso_id": "2",
                                **{f"F{p}_FACTOR": str(v) for p, v in enumerate(
                                    [f8,f9,f10,f11,f12,f13,f14,f15,f16,f17,f18,f19], start=8)
                                }
                            })
                        except Exception:
                            continue
    return rows, "factores"

# -----------------------------
# Preview con “pre-validaciones” + detalles visibles
# -----------------------------
def annotate_preview(rows: list[dict], modo: str):
    """
    Enriquecer 'rows' con:
      - status: 'nuevo'|'actualiza'
      - factores_con_valor, suma_8_19 (string)
      - pre_error / pre_warning (bool)
      - descripcion extendida con detalle de factores/montos y, si corresponde,
        factores DERIVADOS desde montos + suma 8–19 calculada.

    No requiere cambios en templates: la columna 'Descripción' ya se muestra.
    """
    names_map = _factor_names_map()  # opcional para mostrar nombres

    for r in rows:
        try:
            ej = to_int(r.get("ejercicio"))
            se = to_int(r.get("sec_eve"))
            exists = TblCalificacion.objects.filter(ejercicio=ej, secuencia_evento=se).exists()
            r["status"] = "actualiza" if exists else "nuevo"

            base_desc = (r.get("descripcion") or "").strip()
            desc_chunks = [base_desc] if base_desc else []

            factores_con_valor = 0
            suma_8_19 = Decimal("0")
            total_base_montos = Decimal("0")

            # ----- recolectar datos crudos
            factores = {}
            montos = {}
            for k, v in list(r.items()):
                posF = is_factor_col(k)
                posM = is_monto_col(k)
                if posF:
                    val = to_dec(v)
                    factores[posF] = val
                    if val != 0:
                        factores_con_valor += 1
                    if POS_MIN <= posF <= POS_BASE_MAX:
                        suma_8_19 += val
                if posM:
                    m = to_dec(v)
                    montos[posM] = m
                    if POS_MIN <= posM <= POS_BASE_MAX:
                        total_base_montos += m

            # ----- detalle de factores declarados (modo factores)
            if modo == "factores" and factores:
                # Lista compacta y legible
                pares = []
                claves = []
                for pos in sorted(factores):
                    if factores[pos] != 0:
                        pares.append(f"F{pos}={_round8(factores[pos])}")
                        claves.append(f"F{pos}")
                if pares:
                    desc_chunks.append("Detalle(factores): " + ", ".join(pares))
                r["factores_lista"] = ", ".join(claves) if claves else ""
                r["factores_con_valor"] = factores_con_valor
                r["suma_8_19"] = str(_round8(suma_8_19))

            # ----- detalle de montos y factores DERIVADOS (modo montos)
            if modo == "montos" and montos:
                # Montos ingresados
                montos_txt = []
                for pos in sorted(montos):
                    if montos[pos] != 0:
                        montos_txt.append(f"F{pos}=${montos[pos]:,.2f}".replace(",", "X").replace(".", ",").replace("X","."))  # simple localización
                if montos_txt:
                    desc_chunks.append("Detalle(montos): " + ", ".join(montos_txt))

                # Derivar factores
                factores_deriv = {}
                if total_base_montos > 0:
                    for pos in range(POS_MIN, POS_MAX + 1):
                        m = montos.get(pos, Decimal("0"))
                        factores_deriv[pos] = _round8(m / total_base_montos)
                else:
                    for pos in range(POS_MIN, POS_MAX + 1):
                        factores_deriv[pos] = Decimal("0")

                # Sumar 8-19 y listar los > 0
                suma_calc = Decimal("0")
                pares_fact_derived = []
                claves = []
                for pos in range(POS_MIN, POS_MAX + 1):
                    fval = factores_deriv[pos]
                    if POS_MIN <= pos <= POS_BASE_MAX:
                        suma_calc += fval
                    if fval != 0:
                        pares_fact_derived.append(f"F{pos}={fval}")
                        claves.append(f"F{pos}")

                if pares_fact_derived:
                    desc_chunks.append("Factores(derivados): " + ", ".join(pares_fact_derived))
                r["factores_lista"] = ", ".join(claves) if claves else ""
                r["factores_con_valor"] = len(claves)
                r["suma_8_19"] = str(_round8(suma_calc))

            # ----- reglas simples de pre-validación para los banners
            pre_error = False
            pre_warning = False
            if modo == "montos" and total_base_montos <= 0:
                pre_error = True          # no se podrán calcular factores
            if modo == "factores" and suma_8_19 > Decimal("1"):
                pre_error = True          # suma inválida
            if (r.get("mercado_cod") or "").strip() == "" or (r.get("sec_eve") or "").strip() == "":
                pre_warning = True
            if r["status"] == "actualiza":
                pre_warning = True

            r["pre_error"] = pre_error
            r["pre_warning"] = (not pre_error) and pre_warning

            # Unifica la descripción extendida para que se vea en la tabla sin tocar templates
            if desc_chunks:
                r["descripcion"] = " — ".join([c for c in desc_chunks if c])

        except Exception:
            r["status"] = "nuevo"
            r["factores_con_valor"] = 0
            r["suma_8_19"] = "0"
            r["pre_error"] = True
            r["pre_warning"] = False
