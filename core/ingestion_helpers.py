# core/ingestion_helpers.py
from __future__ import annotations

from decimal import Decimal
from datetime import datetime
import csv
import re
from io import TextIOWrapper
from django.utils import timezone

from core.models import TblCalificacion, TblTipoIngreso
# Nota: mantenemos estas constantes desde views.py como en tu versión actual.
from core.views import POS_MIN, POS_BASE_MAX, POS_MAX


# ======================================================================================
# Utilidades generales
# ======================================================================================

def to_int(v, default=0):
    """Convierte a int de forma segura."""
    try:
        return int(str(v).strip())
    except Exception:
        return default


def to_dec(v, default=Decimal("0")):
    """Convierte a Decimal de forma segura (acepta coma o punto)."""
    if v is None or v == "":
        return default
    s = str(v).strip().replace(",", ".")
    try:
        return Decimal(s)
    except Exception:
        return default


def normalize_headers(headers: list[str]) -> list[str]:
    """Normaliza encabezados de CSV (BOM y espacios)."""
    if not headers:
        return []
    h0 = headers[0].lstrip("\ufeff")
    return [h0] + [h.strip() for h in headers[1:]]


def is_factor_col(h: str) -> int | None:
    """
    Identifica columnas de factores con formato 'F<pos>_FACTOR'
    y devuelve la posición (8..37) si aplica.
    """
    H = (h or "").strip().upper()
    if H.startswith("F") and H.endswith("_FACTOR"):
        try:
            pos = int(H[1:H.index("_")])
            return pos if POS_MIN <= pos <= POS_MAX else None
        except Exception:
            return None
    return None


def is_monto_col(h: str) -> int | None:
    """
    Identifica columnas de montos con formato 'F<pos>_MONTO'
    y devuelve la posición (8..37) si aplica.
    """
    H = (h or "").strip().upper()
    if H.startswith("F") and H.endswith("_MONTO"):
        try:
            pos = int(H[1:H.index("_")])
            return pos if POS_MIN <= pos <= POS_MAX else None
        except Exception:
            return None
    return None


def lookup_ci(d: dict, *names):
    """Búsqueda case-insensitive por múltiples aliases."""
    lower = {(k or "").lower(): v for k, v in d.items()}
    for name in names:
        v = lower.get((name or "").lower())
        if v not in (None, ""):
            return v
    return ""


def find_mercado(codigo_o_nombre: str):
    """Busca mercado por código exacto o nombre (case-insensitive)."""
    if not codigo_o_nombre:
        return None
    from core.models import TblMercado
    s = str(codigo_o_nombre).strip()
    m = TblMercado.objects.filter(codigo__iexact=s).first()
    if m:
        return m
    return TblMercado.objects.filter(nombre__iexact=s).first()


def tipo_ingreso_by_id(tipo_id: str | int | None):
    """Obtiene TblTipoIngreso por pk si es válido."""
    if not tipo_id:
        return None
    try:
        return TblTipoIngreso.objects.get(pk=int(tipo_id))
    except Exception:
        return None


# ======================================================================================
# CSV
# ======================================================================================

def parse_csv(io_text: TextIOWrapper):
    """
    Parsea un CSV en modo 'montos' o 'factores' según los headers detectados.
    Devuelve (rows, modo) donde rows es una lista de dicts homogéneos.
    """
    sample = io_text.read(4096)
    io_text.seek(0)
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=[",", ";", "\t"])
    except Exception:
        dialect = csv.excel

    reader = csv.DictReader(io_text, dialect=dialect)
    headers_raw = reader.fieldnames or []
    headers = normalize_headers([h.strip() for h in headers_raw])
    reader.fieldnames = headers

    has_montos = any(is_monto_col(h) for h in headers)
    has_fact = any(is_factor_col(h) for h in headers)
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


# ======================================================================================
# PDF – Certificado 70
#   Parser de texto plano: genera una fila por dividendo.
# ======================================================================================

def _to_money_ch(s: str) -> str:
    """
    Normaliza dinero chileno de texto PDF:
    - '39.546' -> '39546'
    - '1,014'  -> '1.014'
    - quita NBSP, etc.
    """
    if s is None:
        return ""
    s = str(s).strip().replace("\u00a0", " ")
    # factores suelen venir 'x,xxx'
    if re.fullmatch(r"\d+,\d{1,3}", s):
        return s.replace(",", ".")
    # montos con puntos de miles
    return s.replace(".", "").replace(",", ".")


def _to_dec_safe(s: str, default=Decimal("0")) -> Decimal:
    """Convierte usando _to_money_ch, seguro ante errores."""
    try:
        s = _to_money_ch(s)
        return Decimal(s) if s else default
    except Exception:
        return default


def _to_date_ddmmyyyy(s: str):
    """Convierte dd/mm/yyyy a date, corrigiendo OCR simples."""
    if not s:
        return None
    s = s.strip()
    # ejemplo de OCR extraño: '220/02/2020' -> '20/02/2020'
    s = re.sub(r"^2(\d/\d{2}/\d{4})$", r"\1", s)
    try:
        return datetime.strptime(s, "%d/%m/%Y").date()
    except Exception:
        return None


def parse_cert70_text(plain_text: str):
    """
    Extrae múltiples filas desde el PDF (una por dividendo).
    Devuelve (rows, "factores").

    Cada row contiene, al menos:
      - ejercicio, mercado_cod, nemo, fecha_pago, sec_eve, descripcion, tipo_ingreso_id
      - valor_historico, factor_actualizacion, monto_actualizado
      - F8..F19_FACTOR (si no se detectan montos por columna, se asume F8=1, resto 0).
    """
    text = (plain_text or "").replace("\xa0", " ")

    # 1) Ejercicio: lo tomamos de la carátula (varía por formato; usamos dos patrones comunes)
    m_ej = re.search(r"Año Tributario\s+(\d{4})|Ejercicio\s*:?[\s\n]*([12]\d{3})", text, flags=re.I)
    ejercicio = (m_ej.group(1) or m_ej.group(2)) if m_ej else ""

    # Defaults de dominio
    mercado_cod = "ACC"          # Acciones por defecto
    nemo = "PDF-EJEMPLO"
    descripcion = "Desde PDF Cert70"
    tipo_ingreso_id = "2"        # Mantén tu default actual

    rows: list[dict] = []

    # 2) Captura de las filas (una por dividendo) con un regex robusto:
    # RUT  FECHA(dd/mm/yyyy)  MONTO_HIST  FACTOR(x,xxx)  ...  MONTO_ACT  DIVIDENDO_N
    patron = re.compile(
        r"(?P<rut>\d{1,2}\.\d{3}\.\d{3}-[\dkK])\s+"
        r"(?P<fecha>\d{1,2}/\d{1,2}/\d{4})\s+"
        r"(?P<mh>\d{1,3}(?:\.\d{3})*(?:,\d{1,3})?)\s+"
        r"(?P<fac>\d+,\d{1,3})\s+"
        r".{0,30}?"  # columnas intermedias (créditos/otros) que suelen ser ceros
        r"(?P<ma>\d{1,3}(?:\.\d{3})*(?:,\d{1,3})?)\s+"
        r"(?P<div>\d{3,})"
    )

    matches = list(patron.finditer(text))
    for m in matches:
        fecha = _to_date_ddmmyyyy(m.group("fecha"))
        mh = _to_dec_safe(m.group("mh"))
        fac = _to_dec_safe(m.group("fac"))
        ma = _to_dec_safe(m.group("ma"))
        divn = m.group("div")

        r = {
            "ejercicio": ejercicio,
            "mercado_cod": mercado_cod,
            "nemo": nemo,
            "fecha_pago": fecha.isoformat() if fecha else "",
            "sec_eve": divn,                     # usamos “Dividendo N°” como secuencia_evento
            "descripcion": descripcion,
            "tipo_ingreso_id": tipo_ingreso_id,
            "valor_historico": str(mh),
            "factor_actualizacion": str(fac),
            "monto_actualizado": str(ma),
        }

        # Factores 8..19: si el PDF no trae desagregación por fila,
        # dejamos F8=1 y el resto 0 (consistente con tu dominio).
        for pos in range(8, 20):
            r[f"F{pos}_FACTOR"] = "1" if pos == 8 else "0"

        rows.append(r)

    # Fallback: sin coincidencias, mantenemos preview funcional con una fila “dummy”
    if not rows:
        rows = [{
            "ejercicio": ejercicio or "",
            "mercado_cod": mercado_cod,
            "nemo": nemo,
            "fecha_pago": "",
            "sec_eve": "",
            "descripcion": descripcion,
            "tipo_ingreso_id": tipo_ingreso_id,
            "valor_historico": "0",
            "factor_actualizacion": "1.000",
            "monto_actualizado": "0",
            **{f"F{pos}_FACTOR": "0" for pos in range(8, 20)},
        }]

    return rows, "factores"


# ======================================================================================
# Preview con “pre-validaciones”
# ======================================================================================

def annotate_preview(rows: list[dict], modo: str):
    """
    Enriquecemos cada row con:
      - status: 'nuevo' | 'actualiza' (si existe calif misma (ejercicio, secuencia))
      - factores_con_valor
      - suma_8_19
      - pre_error / pre_warning (para pintar tarjetas en la UI)
    """
    from decimal import Decimal as D

    for r in rows:
        try:
            ej = to_int(r.get("ejercicio"))
            se = to_int(r.get("sec_eve"))
            exists = TblCalificacion.objects.filter(ejercicio=ej, secuencia_evento=se).exists()
            r["status"] = "actualiza" if exists else "nuevo"

            factores_con_valor = 0
            suma_8_19 = D("0")
            total_base_montos = D("0")

            for k, v in r.items():
                posF = is_factor_col(k)
                posM = is_monto_col(k)

                if posF:
                    val = to_dec(v)
                    if val != 0:
                        factores_con_valor += 1
                    if POS_MIN <= posF <= POS_BASE_MAX:
                        suma_8_19 += val

                if posM and POS_MIN <= posM <= POS_BASE_MAX:
                    total_base_montos += to_dec(v)

            r["factores_con_valor"] = factores_con_valor
            r["suma_8_19"] = str(suma_8_19)

            # Reglas básicas de aviso/error
            pre_error = False
            pre_warning = False
            if modo == "montos" and total_base_montos <= 0:
                pre_error = True          # no se podrán calcular factores
            if modo == "factores" and suma_8_19 > D("1"):
                pre_error = True          # suma inválida
            if r.get("mercado_cod") == "" or r.get("sec_eve") == "":
                pre_warning = True
            if r["status"] == "actualiza":
                pre_warning = True

            r["pre_error"] = pre_error
            r["pre_warning"] = (not pre_error) and pre_warning

        except Exception:
            r["status"] = "nuevo"
            r["factores_con_valor"] = 0
            r["suma_8_19"] = "0"
            r["pre_error"] = True
            r["pre_warning"] = False
