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

from datetime import datetime

def parse_cert70_text(pdf_file):
    """
    Parsea un PDF Certificado 70 (formato chileno).
    Extrae la tabla de CRÉDITOS de la página 2 como MONTOS.
    
    Args:
        pdf_file: Objeto file (Django UploadedFile)
    
    Returns:
        tuple: (rows, modo) donde rows es lista de dicts y modo es 'montos'
    """
    rows = []
    
    try:
        pdf_file.seek(0)
        
        with pdfplumber.open(pdf_file) as pdf:
            print(f"DEBUG: PDF tiene {len(pdf.pages)} páginas")
            
            for page_num, page in enumerate(pdf.pages, 1):
                print(f"DEBUG: ========== Procesando página {page_num} ==========")
                
                tables = page.extract_tables()
                print(f"DEBUG: Encontradas {len(tables)} tablas en página {page_num}")
                
                for table_num, tbl in enumerate(tables, 1):
                    if not tbl or len(tbl) < 2:
                        continue
                    
                    print(f"DEBUG: Tabla {table_num} - {len(tbl)} filas x {len(tbl[0]) if tbl[0] else 0} columnas")
                    
                    # Identificar si es la tabla de CRÉDITOS (página 2)
                    header_text = ' '.join([str(c) for c in tbl[0] if c]).upper()
                    es_tabla_creditos = "CRÉDITO" in header_text or "CREDITO" in header_text
                    
                    print(f"DEBUG: ¿Es tabla de créditos? {es_tabla_creditos}")
                    
                    if not es_tabla_creditos:
                        print(f"DEBUG: Tabla {table_num} no es de créditos, saltando")
                        continue
                    
                    # Mostrar headers para entender estructura
                    print(f"DEBUG: Headers de tabla de créditos:")
                    for idx, h in enumerate(tbl[0]):
                        print(f"  Col {idx}: {str(h)[:50]}")
                    
                    # Procesar filas de datos (saltar header y footer/totales)
                    for row_idx, row_data in enumerate(tbl[1:], 1):
                        if not row_data:
                            continue
                        
                        # Obtener primera celda para detectar filas válidas
                        primera_celda = str(row_data[0]).strip() if row_data[0] else ""
                        
                        # Saltar filas vacías, headers repetidos y totales
                        if not primera_celda or \
                           "TOTAL" in primera_celda.upper() or \
                           "FECHA" in primera_celda.upper() or \
                           "CRÉDITO" in primera_celda.upper():
                            continue
                        
                        print(f"\nDEBUG: --- Procesando fila {row_idx} ---")
                        print(f"DEBUG: Primera celda: '{primera_celda[:50]}'")
                        print(f"DEBUG: Total columnas en fila: {len(row_data)}")
                        
                        # Dividir celdas multi-línea
                        fechas_raw = primera_celda
                        fechas = [f.strip() for f in fechas_raw.split('\n') if f.strip() and not any(x in f.upper() for x in ['FECHA', 'RETIRO', 'REMESA'])]
                        
                        # Columna 1 = Dividendo Nro
                        div_nros_raw = str(row_data[1]).strip() if len(row_data) > 1 and row_data[1] else ""
                        div_nros = [d.strip() for d in div_nros_raw.split('\n') if d.strip()]
                        
                        if not fechas:
                            print(f"DEBUG: Sin fechas válidas, saltando")
                            continue
                        
                        num_subfilas = len(fechas)
                        print(f"DEBUG: Detectados {num_subfilas} dividendos en esta fila")
                        
                        # Asegurar div_nros tenga valores
                        while len(div_nros) < num_subfilas:
                            div_nros.append(str(len(div_nros) + 1))
                        
                        # Dividir TODAS las columnas
                        columnas_split = []
                        for col_idx, cell in enumerate(row_data):
                            cell_str = str(cell).strip() if cell else ""
                            lineas = [l.strip() for l in cell_str.split('\n')]
                            
                            # Rellenar si faltan líneas
                            while len(lineas) < num_subfilas:
                                lineas.append("")
                            
                            columnas_split.append(lineas)
                        
                        # Procesar cada dividendo (sub-fila)
                        for subfila_idx in range(num_subfilas):
                            try:
                                # Extraer fecha y convertir formato
                                fecha_raw = fechas[subfila_idx] if subfila_idx < len(fechas) else fechas[0]
                                
                                # *** CONVERSIÓN DE FECHA DD/MM/YYYY -> YYYY-MM-DD ***
                                fecha = fecha_raw
                                if '/' in fecha_raw:
                                    try:
                                        partes = fecha_raw.split('/')
                                        if len(partes) == 3:
                                            dia, mes, anio = partes[0], partes[1], partes[2]
                                            fecha_obj = datetime(int(anio), int(mes), int(dia))
                                            fecha = fecha_obj.strftime('%Y-%m-%d')
                                            print(f"DEBUG: Fecha convertida: {fecha_raw} -> {fecha}")
                                    except Exception as e:
                                        print(f"DEBUG: Error convirtiendo fecha '{fecha_raw}': {e}")
                                
                                div_nro = div_nros[subfila_idx] if subfila_idx < len(div_nros) else str(subfila_idx + 1)
                                
                                print(f"DEBUG: Dividendo {subfila_idx+1}/{num_subfilas}: Fecha={fecha}, Div={div_nro}")
                                
                                # MAPEO DE COLUMNAS DEL CERTIFICADO 70 A POSICIONES
                                MAPEO_COLUMNAS = {
                                    2: 8, 3: 9, 4: 10, 5: 11, 6: 12, 7: 13,
                                    8: 14, 9: 15, 10: 16, 11: 17, 12: 18, 13: 19,
                                }
                                
                                # Extraer MONTOS de todas las columnas numéricas
                                montos_dict = {}
                                total_base = Decimal("0")
                                valores_encontrados = []
                                
                                for col_idx in range(2, min(len(columnas_split), 22)):
                                    valor_str = columnas_split[col_idx][subfila_idx].strip()
                                    
                                    if not valor_str or valor_str in ("0", "-", ""):
                                        continue
                                    
                                    # Limpiar formato chileno (puntos miles, comas decimales)
                                    valor_limpio = valor_str.replace(".", "").replace(",", ".")
                                    
                                    try:
                                        val = Decimal(valor_limpio)
                                        if val > 0:
                                            pos_monto = MAPEO_COLUMNAS.get(col_idx, col_idx + 6)
                                            montos_dict[f"F{pos_monto}_MONTO"] = str(val)
                                            
                                            if 8 <= pos_monto <= 19:
                                                total_base += val
                                            valores_encontrados.append(f"F{pos_monto}_MONTO={val} (col{col_idx})")
                                            
                                            print(f"  Col {col_idx}: {valor_str} -> F{pos_monto}_MONTO = {val}")
                                    except (ValueError, Exception) as e:
                                        print(f"  Col {col_idx}: Error convirtiendo '{valor_str}': {e}")
                                        continue
                                
                                # Rellenar con 0 las posiciones faltantes
                                for pos in range(8, 20):
                                    if f"F{pos}_MONTO" not in montos_dict:
                                        montos_dict[f"F{pos}_MONTO"] = "0"
                                
                                print(f"DEBUG: Total base (suma 8-19): {total_base}")
                                print(f"DEBUG: Montos: {valores_encontrados}")
                                
                                # Agregar si hay montos válidos
                                if total_base > 0:
                                    rows.append({
                                        "ejercicio": "2020",
                                        "mercado_cod": "ACC",
                                        "nemo": "CAP",
                                        "fecha_pago": fecha,  # FECHA YA CONVERTIDA
                                        "sec_eve": div_nro,
                                        "descripcion": f"Cert70: {fecha} - Div.{div_nro}",
                                        "tipo_ingreso_id": "2",
                                        **montos_dict
                                    })
                                    print(f"DEBUG: ✓ Dividendo agregado exitosamente")
                                else:
                                    print(f"DEBUG: ✗ Dividendo descartado (total_base=0)")
                                    
                            except Exception as e:
                                print(f"DEBUG: Error procesando dividendo {subfila_idx}: {e}")
                                import traceback
                                traceback.print_exc()
                                continue
        
        print(f"\n{'='*60}")
        print(f"DEBUG: TOTAL FILAS EXTRAÍDAS: {len(rows)}")
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
