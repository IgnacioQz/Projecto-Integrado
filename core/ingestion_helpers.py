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
from core.views.mainv import POS_MIN, POS_BASE_MAX, POS_MAX

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

def parse_cert70_text(pdf_file):
    """
    Parsea un PDF Certificado 70 (formato chileno).
    
    Estructura:
    - Página 1: MONTOS DE DIVIDENDOS → Columnas 8-19 de la tabla → F8_MONTO a F19_MONTO
    - Página 2: CRÉDITOS → Columnas de la tabla → F20_MONTO a F37_MONTO
    
    Args:
        pdf_file: Objeto file (Django UploadedFile)
    
    Returns:
        tuple: (rows, modo) donde rows es lista de dicts y modo es 'montos'
    """
    rows_por_dividendo = {}  # {(fecha, div_nro): {ejercicio, mercado, ..., F8_MONTO, F9_MONTO, ...}}
    
    try:
        pdf_file.seek(0)
        
        with pdfplumber.open(pdf_file) as pdf:            
            for page_num, page in enumerate(pdf.pages, 1):                
                tables = page.extract_tables()
                
                for table_num, tbl in enumerate(tables, 1):
                    if not tbl or len(tbl) < 2:
                        continue
                                        
                    # Identificar tipo de tabla
                    header_text = ' '.join([str(c) for c in tbl[0] if c]).upper()
                    es_tabla_montos = "MONTO" in header_text and "HISTÓRICO" in header_text
                    es_tabla_creditos = "CRÉDITO" in header_text or "CREDITO" in header_text
                    
                    # ============================================================
                    # PÁGINA 1: MONTOS DE DIVIDENDOS (F8-F19)
                    # ============================================================
                    if es_tabla_montos:

                        # Mostrar headers
                        for idx, h in enumerate(tbl[0][:20]):
                            print(f"  Col {idx}: {str(h)[:50]}")
                        
                        # Procesar filas de datos
                        for row_idx, row_data in enumerate(tbl[1:], 1):
                            if not row_data:
                                continue
                            
                            primera_celda = str(row_data[0]).strip() if row_data[0] else ""
                            
                            # Saltar totales y headers
                            if not primera_celda or "TOTAL" in primera_celda.upper():
                                continue
                                                        
                            # Dividir celdas multi-línea
                            fechas_raw = primera_celda
                            fechas = [f.strip() for f in fechas_raw.split('\n') if f.strip() and '/' in f]
                            
                            div_nros_raw = str(row_data[1]).strip() if len(row_data) > 1 and row_data[1] else ""
                            div_nros = [d.strip() for d in div_nros_raw.split('\n') if d.strip()]
                            
                            if not fechas:
                                continue
                            
                            num_subfilas = len(fechas)
                            
                            while len(div_nros) < num_subfilas:
                                div_nros.append(str(len(div_nros) + 1))
                            
                            # Dividir TODAS las columnas
                            columnas_split = []
                            for col_idx, cell in enumerate(row_data):
                                cell_str = str(cell).strip() if cell else ""
                                lineas = [l.strip() for l in cell_str.split('\n')]
                                while len(lineas) < num_subfilas:
                                    lineas.append("")
                                columnas_split.append(lineas)
                            
                            # Procesar cada dividendo
                            for subfila_idx in range(num_subfilas):
                                fecha_raw = fechas[subfila_idx]
                                
                                # Convertir fecha DD/MM/YYYY -> YYYY-MM-DD
                                fecha = fecha_raw
                                if '/' in fecha_raw:
                                    try:
                                        partes = fecha_raw.split('/')
                                        if len(partes) == 3:
                                            dia, mes, anio = partes
                                            fecha_obj = datetime(int(anio), int(mes), int(dia))
                                            fecha = fecha_obj.strftime('%Y-%m-%d')
                                            print(f"DEBUG: Fecha convertida: {fecha_raw} -> {fecha}")
                                    except Exception as e:
                                        print(f"DEBUG: Error convirtiendo fecha: {e}")
                                
                                div_nro = div_nros[subfila_idx]
                                key = (fecha, div_nro)
                                                                
                                # Extraer Secuencia Evento (col 4 - Monto Histórico) y Factor Actualización (col 5)
                                sec_evento = div_nro  # Por defecto usa el div_nro
                                factor_actualizacion = "1"
                                
                                # Col 4 = Secuencia Evento (Monto Histórico)
                                if len(columnas_split) > 4:
                                    sec_str = columnas_split[4][subfila_idx].strip()
                                    if sec_str and sec_str not in ("0", "-", ""):
                                        try:
                                            sec_limpio = sec_str.replace(".", "").replace(",", ".")
                                            sec_evento = sec_limpio
                                            print(f"  Col 4: Secuencia Evento (Monto Histórico) = {sec_evento}")
                                        except:
                                            pass
                                
                                # Col 5 = Factor Actualización
                                if len(columnas_split) > 5:
                                    fa_str = columnas_split[5][subfila_idx].strip()
                                    if fa_str and fa_str not in ("0", "-", ""):
                                        try:
                                            fa_limpio = fa_str.replace(".", "").replace(",", ".")
                                            factor_actualizacion = str(Decimal(fa_limpio))
                                            print(f"  Col 5: Factor Actualización = {factor_actualizacion}")
                                        except:
                                            pass
                                
                                # Inicializar entrada si no existe
                                if key not in rows_por_dividendo:
                                    rows_por_dividendo[key] = {
                                        "ejercicio": "2020",
                                        "mercado_cod": "ACC",
                                        "nemo": "CAP",
                                        "fecha_pago": fecha,
                                        "dividendo": div_nro,  # Col 1: Número de dividendo
                                        "sec_eve": sec_evento,  # Col 4: Monto histórico como secuencia
                                        "descripcion": f"Cert70: {fecha} - Div.{div_nro}",
                                        "tipo_ingreso_id": "2",
                                        "factor_actualizacion": factor_actualizacion,
                                    }
                                
                                # Extraer MONTOS de columnas físicas 7-18 → F8_MONTO a F19_MONTO
                                # Col 7 del PDF = F8, Col 8 = F9, ..., Col 18 = F19
                                for col_pdf in range(7, 19):  # Columnas físicas 7-18 (12 columnas)
                                    if col_pdf >= len(columnas_split):
                                        break
                                    
                                    pos_factor = col_pdf + 1  # col 7→F8, col 8→F9, ..., col 18→F19
                                    valor_str = columnas_split[col_pdf][subfila_idx].strip()
                                    
                                    if not valor_str or valor_str in ("0", "-", ""):
                                        rows_por_dividendo[key][f"F{pos_factor}_MONTO"] = "0"
                                        continue
                                    
                                    # Limpiar formato chileno
                                    valor_limpio = valor_str.replace(".", "").replace(",", ".")
                                    
                                    try:
                                        val = Decimal(valor_limpio)
                                        rows_por_dividendo[key][f"F{pos_factor}_MONTO"] = str(val)
                                        print(f"  Col {col_pdf} (Página 1): {valor_str} -> F{pos_factor}_MONTO = {val}")
                                    except Exception as e:
                                        rows_por_dividendo[key][f"F{pos_factor}_MONTO"] = "0"
                                        print(f"  Col {col_pdf}: Error - {e}")
                    
                    # ============================================================
                    # PÁGINA 2: CRÉDITOS (F20-F37)
                    # ============================================================
                    elif es_tabla_creditos:
                        # Mostrar headers
                        for idx, h in enumerate(tbl[0][:20]):
                            print(f"  Col {idx}: {str(h)[:50]}")
                        
                        # MAPEO: columnas físicas del PDF → posiciones F20-F37
                        # Col 2 del PDF = F20, Col 3 = F21, ..., Col 19 = F37
                        MAPEO_CREDITOS = {
                            2: 20,   # Col 2 → F20
                            3: 21,   # Col 3 → F21
                            4: 22,
                            5: 23,
                            6: 24,
                            7: 25,   # Aquí está el valor 6.525.197
                            8: 26,
                            9: 27,
                            10: 28,
                            11: 29,
                            12: 30,
                            13: 31,
                            14: 32,
                            15: 33,
                            16: 34,
                            17: 35,
                            18: 36,
                            19: 37,  # Col 19 → F37
                        }
                        
                        # Procesar filas
                        for row_idx, row_data in enumerate(tbl[1:], 1):
                            if not row_data:
                                continue
                            
                            primera_celda = str(row_data[0]).strip() if row_data[0] else ""
                            
                            if not primera_celda or "TOTAL" in primera_celda.upper():
                                continue
                                                        
                            # Dividir celdas
                            fechas_raw = primera_celda
                            fechas = [f.strip() for f in fechas_raw.split('\n') if f.strip() and '/' in f]
                            
                            div_nros_raw = str(row_data[1]).strip() if len(row_data) > 1 and row_data[1] else ""
                            div_nros = [d.strip() for d in div_nros_raw.split('\n') if d.strip()]
                            
                            if not fechas:
                                continue
                            
                            num_subfilas = len(fechas)
                            
                            while len(div_nros) < num_subfilas:
                                div_nros.append(str(len(div_nros) + 1))
                            
                            columnas_split = []
                            for col_idx, cell in enumerate(row_data):
                                cell_str = str(cell).strip() if cell else ""
                                lineas = [l.strip() for l in cell_str.split('\n')]
                                while len(lineas) < num_subfilas:
                                    lineas.append("")
                                columnas_split.append(lineas)
                            
                            # Procesar cada dividendo
                            for subfila_idx in range(num_subfilas):
                                fecha_raw = fechas[subfila_idx]
                                
                                # Convertir fecha
                                fecha = fecha_raw
                                if '/' in fecha_raw:
                                    try:
                                        partes = fecha_raw.split('/')
                                        if len(partes) == 3:
                                            dia, mes, anio = partes
                                            fecha_obj = datetime(int(anio), int(mes), int(dia))
                                            fecha = fecha_obj.strftime('%Y-%m-%d')
                                    except:
                                        pass
                                
                                div_nro = div_nros[subfila_idx]
                                key = (fecha, div_nro)
                                                                
                                # Buscar la entrada existente de página 1
                                if key not in rows_por_dividendo:
                                    print(f"WARNING: No se encontró entrada de página 1 para {key}")
                                    rows_por_dividendo[key] = {
                                        "ejercicio": "2020",
                                        "mercado_cod": "ACC",
                                        "nemo": "CAP",
                                        "fecha_pago": fecha,
                                        "sec_eve": div_nro,
                                        "descripcion": f"Cert70: {fecha} - Div.{div_nro}",
                                        "tipo_ingreso_id": "2",
                                    }
                                
                                # Extraer CRÉDITOS → F20-F37
                                for col_idx, pos_factor in MAPEO_CREDITOS.items():
                                    if col_idx >= len(columnas_split):
                                        break
                                    
                                    valor_str = columnas_split[col_idx][subfila_idx].strip()
                                    
                                    if not valor_str or valor_str in ("0", "-", ""):
                                        rows_por_dividendo[key][f"F{pos_factor}_MONTO"] = "0"
                                        continue
                                    
                                    valor_limpio = valor_str.replace(".", "").replace(",", ".")
                                    
                                    try:
                                        val = Decimal(valor_limpio)
                                        rows_por_dividendo[key][f"F{pos_factor}_MONTO"] = str(val)
                                        print(f"  Col {col_idx} (Página 2): {valor_str} -> F{pos_factor}_MONTO = {val}")
                                    except Exception as e:
                                        rows_por_dividendo[key][f"F{pos_factor}_MONTO"] = "0"
        
        # Convertir dict a lista y rellenar posiciones faltantes
        rows = []
        for key, row_data in rows_por_dividendo.items():
            # Asegurar que todas las posiciones F8-F37 existan
            for pos in range(8, 38):
                if f"F{pos}_MONTO" not in row_data:
                    row_data[f"F{pos}_MONTO"] = "0"
            rows.append(row_data)
        
        print(f"\n{'='*60}")
        for row in rows:
            montos_keys = [k for k in row.keys() if '_MONTO' in k and row[k] != '0']
            print(f"  {row['fecha_pago']} Div.{row['sec_eve']}: {len(montos_keys)} montos con valores")
        print(f"{'='*60}")
        
    except Exception as e:
        print(f"ERROR CRÍTICO al procesar PDF: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
    
    return rows, "montos"

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
