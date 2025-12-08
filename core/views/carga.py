from __future__ import annotations

# ============================================================================
# IMPORTS
# ============================================================================
import os
from io import TextIOWrapper, BytesIO
from decimal import Decimal as D

import pdfplumber
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
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
SESSION_FILE = "upload_file_content"      # contenido del archivo en bytes (para subir después)


# ============================================================================
# HELPERS LOCALES
# ============================================================================
def _clear_upload_session(request) -> None:
    """Borra las claves de sesión usadas para la carga/preview."""
    for key in (SESSION_ROWS, SESSION_MODE, SESSION_META, SESSION_FILE):
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
    
    Flujo NUEVO:
      1. Lee y parsea el archivo (CSV o PDF)
      2. Valida el contenido
      3. Guarda el contenido en SESIÓN (no en S3 todavía)
      4. Muestra vista previa
      5. Solo cuando el usuario confirma en carga_confirmar(), se sube a S3
    
    Esto evita subir archivos con errores a S3.
    """
    # POST con archivo: procesar
    if request.method == "POST" and request.FILES.get("archivo"):
        upload = request.FILES["archivo"]
        fname = upload.name
        ext = _ext(fname)

        # Solo aceptamos CSV o PDF
        if ext not in (".csv", ".pdf"):
            messages.error(request, "Sube un archivo .csv o .pdf.")
            return render(request, "calificaciones/carga_archivo.html")

        tipo_archivo = "csv" if ext == ".csv" else "pdf"

        try:
            # Leer todo el contenido del archivo a memoria
            if hasattr(upload, "seek"):
                upload.seek(0)
            file_content = upload.read()
            
            # Volver al inicio para procesamiento
            if hasattr(upload, "seek"):
                upload.seek(0)

            # --- CSV ---
            if ext == ".csv":
                wrapper = TextIOWrapper(BytesIO(file_content), encoding="utf-8", newline="")
                rows, modo = parse_csv(wrapper)
                wrapper.detach()

            # --- PDF (Certificado 70) ---
            else:

                
                # Crear un objeto file-like desde bytes para pdfplumber
                pdf_file_like = BytesIO(file_content)
                rows, modo = parse_cert70_text(pdf_file_like)

            # Debe haber filas válidas
            if not rows:
                print("DEBUG: No se detectaron filas válidas")
                messages.warning(request, "No se detectaron filas válidas.")
                return render(request, "calificaciones/carga_archivo.html")

            # Anota errores/advertencias y campos auxiliares para el preview
            annotate_preview(rows, modo)

            # Guardamos datos en sesión para la confirmación
            # IMPORTANTE: Guardamos el contenido del archivo en sesión (en formato base64 o bytes)
            import base64
            request.session[SESSION_FILE] = base64.b64encode(file_content).decode('utf-8')
            request.session[SESSION_ROWS] = rows
            request.session[SESSION_MODE] = modo
            request.session[SESSION_META] = {
                "nombre": fname,
                "tipo": tipo_archivo,
            }
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
            print(f"DEBUG ERROR: {ex}")
            import traceback
            traceback.print_exc()
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
    
    Flujo NUEVO:
      1. Valida que no hay errores
      2. PRIMERO sube el archivo a S3
      3. Crea el registro TblArchivoFuente con la URL de S3
      4. Procesa y guarda las calificaciones en BD
      5. Si algo falla, hace rollback de BD pero el archivo YA está en S3
    
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
    file_content_b64 = request.session.get(SESSION_FILE)

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

    # Debe existir el contenido del archivo en sesión
    if not file_content_b64:
        messages.error(request, "No se encontró el archivo en sesión.")
        return redirect("carga_archivo")

    # ============================================================================
    # PASO 1: VERIFICAR DUPLICIDAD Y SUBIR ARCHIVO A S3
    # ============================================================================
    try:
        import base64
        import hashlib
        from datetime import datetime
        
        file_content = base64.b64decode(file_content_b64)
        fname = meta.get("nombre", "upload")
        
        # Calcular hash SHA256 del contenido
        file_hash = hashlib.sha256(file_content).hexdigest()
        
        # Buscar si ya existe un archivo con el mismo hash
        archivo_existente = TblArchivoFuente.objects.filter(
            hash_contenido=file_hash
        ).first()
        
        if archivo_existente:
            # Archivo duplicado encontrado - reutilizar
            archivo_fuente = archivo_existente
            print(f": Archivo duplicado encontrado (ID: {archivo_fuente.archivo_fuente_id})")
            
            # Convertir UTC a hora Chile (restar 3 horas)
            from datetime import timedelta
            fecha_chile = archivo_fuente.fecha_subida - timedelta(hours=3)
            
            messages.info(
                request, 
                f"El archivo ya fue cargado anteriormente el {fecha_chile.strftime('%d/%m/%Y %H:%M')}. "
                f"Se reutilizará el archivo existente."
            )
        else:
            # Archivo nuevo - subir a S3
            # Generar nombre único con timestamp para evitar colisiones
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            nombre_unico = f"{timestamp}_{fname}"
            
            s3_key = default_storage.save(
                f"calificaciones/{nombre_unico}",
                ContentFile(file_content)
            )
            
            try:
                file_url = default_storage.url(s3_key)
            except Exception:
                file_url = s3_key
            
            # Crear registro de archivo fuente
            archivo_fuente = TblArchivoFuente.objects.create(
                nombre_archivo=fname,
                ruta_almacenamiento=file_url,
                hash_contenido=file_hash,
                tamanio_bytes=len(file_content),
                usuario=request.user,
            )
                    
    except Exception as ex:
        messages.error(request, f"Error al procesar archivo: {ex}")
        return redirect("carga_archivo")

    # ============================================================================
    # PASO 2: PROCESAR Y GUARDAR CALIFICACIONES EN BD
    # ============================================================================
    def_map = _build_def_map()   # Catálogo {pos: TblFactorDef}
    created = updated = skipped = 0
    errores: list[str] = []

    # Transacción: todo o nada por consistencia
    with transaction.atomic():
        for i, r in enumerate(rows, start=1):
            try:
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
                    calif.archivo_fuente = archivo_fuente
                    calif.save(update_fields=[
                        "mercado", "instrumento_text", "tipo_ingreso", "descripcion",
                        "fecha_pago_dividendo", "usuario", "archivo_fuente"
                    ])

                # ----------------- Persistencia de factores -----------------                
                # Modo 'montos' -> calcula factores proporcionalmente a total (8..19)
                if modo == "montos":
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

                # Modo 'factors' -> valida suma 8..19 <= 1 y guarda tal cual
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