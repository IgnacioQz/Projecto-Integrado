# core/views.py
from decimal import Decimal, ROUND_HALF_UP
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.db import models, transaction
from django.shortcuts import render, redirect, get_object_or_404

from .models import TblCalificacion, TblFactorValor, TblFactorDef, TblTipoIngreso, TblMercado
from .forms import CalificacionBasicaForm, MontosForm, FactoresForm

# =============================================================================
# Funciones de utilidad
# =============================================================================
def _round8(x: Decimal) -> Decimal:
    """
    Redondea un número decimal a 8 decimales usando HALF_UP.
    Args:
        x (Decimal): Número a redondear
    Returns:
        Decimal: Número redondeado a 8 decimales
    """
    return x.quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP)

# =============================================================================
# Vistas de autenticación y navegación básica
# =============================================================================
def welcome_view(request):
    """Página de inicio pública."""
    return render(request, "welcome.html")

def login_view(request):
    """
    Maneja la autenticación de usuarios.
    - GET: Muestra el formulario de login
    - POST: Valida credenciales y crea sesión
    """
    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "").strip()

        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            return redirect("main")
        messages.error(request, "Usuario o contraseña incorrectos.")
    return render(request, "login.html")

def logout_view(request):
    """Cierra la sesión del usuario y redirecciona a welcome."""
    logout(request)
    return redirect("welcome")

# =============================================================================
# Vista principal y gestión de calificaciones
# =============================================================================
@login_required(login_url="login")
def main_view(request):
    """Dashboard principal con listado de calificaciones y filtros."""
    filtro_mercado = request.GET.get('mercado', '')
    filtro_tipo_ingreso = request.GET.get('tipo_ingreso', '')
    filtro_ejercicio = request.GET.get('ejercicio', '')

    qs = (TblCalificacion.objects
          .select_related('mercado', 'tipo_ingreso')
          # prefetch el conjunto de factores (ajusta 'factores' si tu related_name es distinto)
          .prefetch_related('factores'))

    if filtro_mercado:
        qs = qs.filter(mercado_id=filtro_mercado)
    if filtro_tipo_ingreso:
        qs = qs.filter(tipo_ingreso_id=filtro_tipo_ingreso)
    if filtro_ejercicio:
        try:
            qs = qs.filter(ejercicio=int(filtro_ejercicio))
        except ValueError:
            pass

    items = qs.order_by('-fecha_creacion')[:500]  # limita por seguridad

    # construir estructuras fáciles de usar en plantilla
    for it in items:
        # obtener queryset de factores: intenta related_name 'factores' y si no existe usa reverse relation por convención
        try:
            factor_qs = it.factores.all()
        except Exception:
            factor_qs = it.tblfactorvalor_set.all()

        factores_map = {int(f.posicion): f.valor for f in factor_qs}
        # lista indexada: índice 0 -> posición 8, índice 29 -> posición 37
        factores_array = [factores_map.get(pos) for pos in range(8, 38)]

        it.factores_map = factores_map
        it.factores_array = factores_array

    context = {
        'items': items,
        'mercados_disponibles': TblMercado.objects.filter(activo=True).order_by('nombre'),
        'tipos_ingreso_disponibles': TblTipoIngreso.objects.all().order_by('nombre_tipo_ingreso'),
        'ejercicios_disponibles': TblCalificacion.objects.values_list('ejercicio', flat=True).distinct().order_by('-ejercicio'),
        'filtro_mercado': filtro_mercado,
        'filtro_tipo_ingreso': filtro_tipo_ingreso,
        'filtro_ejercicio': filtro_ejercicio,
    }
    return render(request, "main.html", context)

# =============================================================================
# Gestión de calificaciones - Carga Manual
# =============================================================================
@login_required(login_url="login")
def carga_manual_view(request):
    """PASO 1: Crear nueva calificación."""
    if request.method == "POST":
        form = CalificacionBasicaForm(request.POST)
        if form.is_valid():
            calif = form.save(commit=False)
            calif.usuario = request.user
            calif.save()
            messages.success(request, "✅ Calificación creada correctamente.")
            return redirect("calificacion_edit", pk=calif.pk)
    else:
        form = CalificacionBasicaForm()

    # Añadir mercados disponibles al contexto
    mercados = TblMercado.objects.filter(activo=True).order_by('nombre')
    
    return render(request, "cargaManual.html", {
        "form": form,
        "mercados": mercados,
    })

@login_required(login_url="login")
@transaction.atomic
def calificacion_edit(request, pk: int):
    """
    PASO 2: Edición de montos/factores y cálculo
    - Modo MONTOS: Ingresa montos, calcula factores automáticamente
    - Modo FACTORES: Ingresa factores manualmente
    - Valida reglas de negocio (suma <= 1.00000000)
    - Permite edición completa de calificaciones existentes
    """
    calif = get_object_or_404(TblCalificacion, pk=pk)

    # Catálogo de factores
    defs_qs = (
        TblFactorDef.objects
        .filter(posicion__gte=8, posicion__lte=37, activo=True)
        .order_by("posicion")
    )
    def_map = {d.posicion: d for d in defs_qs}

    # Carga inicial de datos existentes
    initial_montos = {
        f"monto_{fv.posicion}": fv.monto_base
        for fv in calif.factores.filter(posicion__gte=8, posicion__lte=37)
    }
    
    initial_factores = {
        f"factor_{fv.posicion}": fv.valor
        for fv in calif.factores.filter(posicion__gte=8, posicion__lte=37)
    }

    # Determinar modo de ingreso (por defecto: montos)
    modo_ingreso = request.POST.get("modo_ingreso", request.GET.get("modo_ingreso", "montos"))

    if request.method == "POST":
        action = request.POST.get("action")
        
        # =====================================================
        # ACCIÓN: ELIMINAR CALIFICACIÓN COMPLETA
        # =====================================================
        if action == "eliminar":
            calif_id = calif.calificacion_id
            calif.delete()
            messages.success(
                request, 
                f"🗑️ Calificación #{calif_id} eliminada permanentemente."
            )
            return redirect("main")
        
        # =====================================================
        # ACCIÓN: CANCELAR (volver sin guardar)
        # =====================================================
        if action == "cancelar":
            messages.info(request, "Edición cancelada. No se guardaron cambios.")
            return redirect("main")

        # =====================================================
        # MODO: INGRESAR MONTOS (cálculo automático)
        # =====================================================
        if modo_ingreso == "montos":
            montos_form = MontosForm(request.POST, factor_defs=def_map)
            factores_form = FactoresForm(initial=initial_factores, factor_defs=def_map)

            if montos_form.is_valid():
                total = montos_form.total_8_19()
                
                # Validación: al menos un monto > 0
                if total <= 0:
                    messages.error(
                        request, 
                        "❌ Debes ingresar al menos un monto mayor a 0 en las posiciones 8-19."
                    )
                    return render(
                        request,
                        "calificaciones_edit.html",
                        {
                            "calif": calif,
                            "montos_form": montos_form,
                            "factores_form": factores_form,
                            "def_map": def_map,
                            "modo_ingreso": modo_ingreso,
                        },
                    )

                # Calcular factores
                factores = {}
                suma_8_19 = Decimal("0")
                for pos in range(8, 38):
                    monto = montos_form.cleaned_data.get(f"monto_{pos}") or Decimal("0")
                    factor = _round8(monto / total) if total > 0 else Decimal("0")
                    factores[pos] = {
                        "monto": monto,
                        "factor": factor,
                        "nombre": def_map[pos].nombre if pos in def_map else str(pos),
                    }
                    if 8 <= pos <= 19:
                        suma_8_19 += factor

                # Validar suma <= 1
                suma_valida = suma_8_19 <= Decimal("1.00000000")
                if not suma_valida:
                    messages.error(
                        request,
                        f"❌ La suma de factores 8-19 = {suma_8_19} supera 1.00000000.",
                    )
                    return render(
                        request,
                        "calificaciones_edit.html",
                        {
                            "calif": calif,
                            "montos_form": montos_form,
                            "factores_form": factores_form,
                            "factores": factores,
                            "total": total,
                            "suma_factores_8_19": suma_8_19,
                            "suma_valida": suma_valida,
                            "def_map": def_map,
                            "modo_ingreso": modo_ingreso,
                        },
                    )

                # CALCULAR (mostrar resultados sin guardar)
                if action == "calcular":
                    messages.info(
                        request, 
                        "✅ Cálculo realizado. Revisa y pulsa Guardar para persistir."
                    )
                    return render(
                        request,
                        "calificaciones_edit.html",
                        {
                            "calif": calif,
                            "montos_form": montos_form,
                            "factores_form": factores_form,
                            "factores": factores,
                            "total": total,
                            "suma_factores_8_19": suma_8_19,
                            "suma_valida": suma_valida,
                            "def_map": def_map,
                            "modo_ingreso": modo_ingreso,
                        },
                    )

                # GUARDAR
                if action == "guardar":
                    for pos, row in factores.items():
                        TblFactorValor.objects.update_or_create(
                            calificacion=calif,
                            posicion=pos,
                            defaults={
                                "monto_base": row["monto"],
                                "valor": row["factor"],
                            },
                        )
                    
                    # Actualizar usuario (fecha_modificacion se actualiza automáticamente con auto_now)
                    calif.usuario = request.user
                    calif.save(update_fields=["usuario"])

                    messages.success(
                        request, 
                        "✅ Calificación guardada. Montos y factores actualizados correctamente."
                    )
                    return redirect("main")

            # Formulario con errores
            factores_form = FactoresForm(initial=initial_factores, factor_defs=def_map)
            return render(
                request,
                "calificaciones_edit.html",
                {
                    "calif": calif,
                    "montos_form": montos_form,
                    "factores_form": factores_form,
                    "def_map": def_map,
                    "modo_ingreso": modo_ingreso,
                },
            )

        # =====================================================
        # MODO: INGRESAR FACTORES (manual)
        # =====================================================
        elif modo_ingreso == "factores":
            montos_form = MontosForm(initial=initial_montos, factor_defs=def_map)
            factores_form = FactoresForm(request.POST, factor_defs=def_map)

            if factores_form.is_valid():
                # Recopilar factores ingresados
                factores = {}
                suma_8_19 = Decimal("0")
                
                for pos in range(8, 38):
                    factor = factores_form.cleaned_data.get(f"factor_{pos}") or Decimal("0")
                    factores[pos] = {
                        "factor": factor,
                        "nombre": def_map[pos].nombre if pos in def_map else str(pos),
                    }
                    if 8 <= pos <= 19:
                        suma_8_19 += factor

                # Validar suma <= 1
                suma_valida = suma_8_19 <= Decimal("1.00000000")
                
                if not suma_valida:
                    messages.error(
                        request,
                        f"❌ La suma de factores 8-19 = {suma_8_19} supera 1.00000000. "
                        f"Ajusta los valores antes de guardar."
                    )

                # VALIDAR (mostrar resultados sin guardar)
                if action == "validar":
                    if suma_valida:
                        messages.success(
                            request, 
                            f"✅ Validación exitosa. Suma = {suma_8_19}. Pulsa Guardar para persistir."
                        )
                    return render(
                        request,
                        "calificaciones_edit.html",
                        {
                            "calif": calif,
                            "montos_form": montos_form,
                            "factores_form": factores_form,
                            "factores": factores,
                            "suma_factores_8_19": suma_8_19,
                            "suma_valida": suma_valida,
                            "def_map": def_map,
                            "modo_ingreso": modo_ingreso,
                        },
                    )

                # GUARDAR
                if action == "guardar":
                    if not suma_valida:
                        messages.error(
                            request,
                            "❌ No se puede guardar. La suma de factores 8-19 excede 1.0"
                        )
                        return render(
                            request,
                            "calificaciones_edit.html",
                            {
                                "calif": calif,
                                "montos_form": montos_form,
                                "factores_form": factores_form,
                                "factores": factores,
                                "suma_factores_8_19": suma_8_19,
                                "suma_valida": suma_valida,
                                "def_map": def_map,
                                "modo_ingreso": modo_ingreso,
                            },
                        )
                    
                    # Guardar factores manuales (sin monto_base)
                    for pos, row in factores.items():
                        TblFactorValor.objects.update_or_create(
                            calificacion=calif,
                            posicion=pos,
                            defaults={
                                "monto_base": None,  # No hay montos en modo manual
                                "valor": row["factor"],
                            },
                        )
                    
                    # Actualizar usuario (fecha_modificacion se actualiza automáticamente)
                    calif.usuario = request.user
                    calif.save(update_fields=["usuario"])

                    messages.success(
                        request, 
                        "✅ Factores guardados manualmente. Calificación actualizada."
                    )
                    return redirect("main")

            # Formulario con errores
            montos_form = MontosForm(initial=initial_montos, factor_defs=def_map)
            return render(
                request,
                "calificaciones_edit.html",
                {
                    "calif": calif,
                    "montos_form": montos_form,
                    "factores_form": factores_form,
                    "def_map": def_map,
                    "modo_ingreso": modo_ingreso,
                },
            )

    # =====================================================
    # GET: Carga inicial del formulario
    # =====================================================
    montos_form = MontosForm(initial=initial_montos, factor_defs=def_map)
    factores_form = FactoresForm(initial=initial_factores, factor_defs=def_map)
    
    # Advertencia si no tiene factores guardados (calificación nueva/incompleta)
    if not calif.factores.exists():
        messages.warning(
            request,
            "⚠️ Esta calificación está INCOMPLETA. Debes ingresar y guardar los montos/factores."
        )
    
    return render(
        request,
        "calificaciones_edit.html",
        {
            "calif": calif,
            "montos_form": montos_form,
            "factores_form": factores_form,
            "def_map": def_map,
            "modo_ingreso": modo_ingreso,
        },
    )
# =============================================================================
# Carga Masiva (placeholder)
# =============================================================================
def carga_masiva_view(request):
    """Vista para carga masiva de calificaciones (pendiente implementar)"""
    return render(request, "cargaMasiva.html")


# =============================================================================
# Sandbox (menú de pruebas funcionales reales)
# =============================================================================



# =============================================================================
# Listado de calificaciones (sandbox)
# =============================================================================
@login_required(login_url="login")
def calificacion_list(request):
    """
    Lista últimas calificaciones creadas/modificadas.
    - Ordena por fecha de creación desc.
    - Limita a 200 como paginación rudimentaria.
    """
    items = TblCalificacion.objects.order_by("-fecha_creacion")[:200]
    return render(request, "calificaciones_list.html", {"items": items})


# =============================================================================
# PASO 1: Crear calificación (datos base)
# -----------------------------------------------------------------------------
# Se usa transacción atómica por si en el futuro añades pasos adicionales
# (p.ej. crear logs, inicializar detalle, etc.). Si algo falla, hace rollback.
# =============================================================================
@login_required(login_url="login")
@transaction.atomic
def calificacion_create(request):
    """
    GET  -> muestra form con campos base de TblCalificacion
    POST -> valida y persiste; setea `usuario` con request.user;
            redirige al PASO 2 para ingresar montos por factor.
    """
    if request.method == "POST":
        form = CalificacionBasicaForm(request.POST)
        if form.is_valid():
            calif = form.save(commit=False)
            calif.usuario = request.user  # trazabilidad: quién creó/modificó
            calif.save()

            messages.success(
                request,
                "Calificación creada. Continúa con los montos por factor."
            )
            # Redirige al PASO 2 (edición de montos 8..37)
            return redirect("calificacion_edit", pk=calif.pk)

        # Form inválido -> re-render con errores
        return render(request, "calificaciones_form.html", {"form": form})

    # GET
    return render(request, "calificaciones_form.html", {"form": CalificacionBasicaForm()})


@login_required(login_url="login")
@transaction.atomic
def calificacion_delete(request, pk: int):
    """
    Elimina una calificación específica (individual).
    """
    calif = get_object_or_404(TblCalificacion, pk=pk)
    
    if request.method == "POST":
        calif_id = calif.calificacion_id
        calif.delete()
        messages.success(request, f"✅ Calificación #{calif_id} eliminada correctamente.")
        return redirect("main")
    
    # GET: mostrar confirmación (usar el template existente)
    return render(request, "calificaciones_confirm_deleted.html", {"calif": calif})


@login_required(login_url="login")
@transaction.atomic
def calificacion_delete_multiple(request):
    """
    Elimina múltiples calificaciones seleccionadas (desde checkboxes).
    Recibe una lista de IDs por POST.
    """
    if request.method == "POST":
        # Obtener IDs desde el POST
        ids = request.POST.getlist('ids[]')  # Lista de IDs como strings
        
        if not ids:
            messages.error(request, "❌ No se seleccionaron calificaciones para eliminar.")
            return redirect("main")
        
        # Convertir a enteros
        ids = [int(id) for id in ids]
        
        # Eliminar las calificaciones
        calificaciones = TblCalificacion.objects.filter(pk__in=ids)
        count = calificaciones.count()
        
        if count == 0:
            messages.error(request, "❌ No se encontraron las calificaciones seleccionadas.")
            return redirect("main")
        
        calificaciones.delete()
        
        messages.success(
            request, 
            f"✅ {count} calificación{'es' if count > 1 else ''} eliminada{'s' if count > 1 else ''} correctamente."
        )
        return redirect("main")
    
    # Si no es POST, redirigir
    return redirect("main")