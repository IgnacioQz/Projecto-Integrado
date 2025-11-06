# core/views.py
from decimal import Decimal, ROUND_HALF_UP
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.db import models, transaction
from django.shortcuts import render, redirect, get_object_or_404

from .models import TblCalificacion, TblFactorValor, TblFactorDef, TblTipoIngreso
from .forms import CalificacionBasicaForm, MontosForm

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
    """
    Dashboard principal con listado de calificaciones y filtros.
    Permite filtrar por:
    - Mercado
    - Tipo de ingreso
    - Ejercicio
    """
    # Obtener y procesar filtros
    filtro_mercado = request.GET.get('mercado', '').strip()
    filtro_tipo_ingreso = request.GET.get('tipo_ingreso', '').strip()
    filtro_ejercicio = request.GET.get('ejercicio', '').strip()
    
    # Query base optimizada
    items = (TblCalificacion.objects
             .select_related('tipo_ingreso', 'instrumento')
             .prefetch_related('factores'))
    
    # Aplicar filtros si existen
    if filtro_mercado:
        items = items.filter(mercado__icontains=filtro_mercado)
    if filtro_tipo_ingreso:
        items = items.filter(tipo_ingreso__nombre_tipo_ingreso__icontains=filtro_tipo_ingreso)
    if filtro_ejercicio:
        try:
            items = items.filter(ejercicio=int(filtro_ejercicio))
        except ValueError:
            pass
    
    items = items.order_by('-fecha_creacion')[:200]
    
    # Procesar factores para cada calificación
    for item in items:
        all_factores = list(item.factores.all())
        item.factores_dict = {
            f.posicion: f.valor 
            for f in all_factores
            if 8 <= f.posicion <= 37
        }
    
    # Obtener opciones para filtros
    context = {
        'items': items,
        'filtro_mercado': filtro_mercado,
        'filtro_tipo_ingreso': filtro_tipo_ingreso,
        'filtro_ejercicio': filtro_ejercicio,
        'mercados_disponibles': TblCalificacion.objects.values_list('mercado', flat=True).distinct().order_by('mercado'),
        'tipos_ingreso_disponibles': TblTipoIngreso.objects.all().order_by('nombre_tipo_ingreso'),
        'ejercicios_disponibles': TblCalificacion.objects.values_list('ejercicio', flat=True).distinct().order_by('-ejercicio'),
    }
    
    return render(request, "main.html", context)

# =============================================================================
# Gestión de calificaciones - Carga Manual
# =============================================================================
@login_required(login_url="login")
@transaction.atomic
def carga_manual_view(request):
    """
    PASO 1: Crear nueva calificación (datos básicos)
    - GET: Muestra formulario vacío
    - POST: Valida y crea calificación parcial
    """
    if request.method == "POST":
        form = CalificacionBasicaForm(request.POST)
        if form.is_valid():
            calif = form.save(commit=False)
            calif.usuario = request.user
            calif.save()
            messages.warning(request, "⚠️ Calificación creada PARCIALMENTE. Complete el paso 2.")
            return redirect("calificacion_edit", pk=calif.pk)
        messages.error(request, "Por favor corrija los errores en el formulario.")
        return render(request, "cargaManual.html", {"form": form})

    form = CalificacionBasicaForm()
    return render(request, "cargaManual.html", {"form": form})

@login_required(login_url="login")
@transaction.atomic
def calificacion_edit(request, pk: int):
    """
    PASO 2: Edición de montos y cálculo de factores
    - Permite ingresar montos para posiciones 8-37
    - Calcula factores basados en el total
    - Valida reglas de negocio (suma <= 1.00000000)
    """
    calif = get_object_or_404(TblCalificacion, pk=pk)

    # Catálogo de factores
    defs_qs = (
        TblFactorDef.objects
        .filter(posicion__gte=8, posicion__lte=37, activo=True)
        .order_by("posicion")
    )
    def_map = {d.posicion: d for d in defs_qs}

    # Carga inicial de montos
    initial = {
        f"monto_{fv.posicion}": fv.monto_base
        for fv in calif.factores.filter(posicion__gte=8, posicion__lte=37)
    }

    if request.method == "POST":
        action = request.POST.get("action")
        
        # Acción CANCELAR: Eliminar calificación incompleta
        if action == "cancelar":
            if not calif.factores.exists():
                calif.delete()
                messages.info(request, "🗑️ Calificación incompleta eliminada.")
            else:
                messages.warning(request, "No se puede eliminar una calificación con factores guardados.")
            return redirect("main")
        
        montos_form = MontosForm(request.POST, factor_defs=def_map)

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
                    {"calif": calif, "montos_form": montos_form, "def_map": def_map},
                )

            # Calcular factores
            factores = {}
            suma_8_19 = Decimal("0")
            for pos in range(8, 38):
                monto = montos_form.cleaned_data.get(f"monto_{pos}") or Decimal("0")
                factor = _round8(monto / total)
                factores[pos] = {
                    "monto": monto,
                    "factor": factor,
                    "nombre": def_map[pos].nombre if pos in def_map else str(pos),
                }
                if 8 <= pos <= 19:
                    suma_8_19 += factor

            # Validar suma <= 1
            if suma_8_19 > Decimal("1.00000000"):
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
                        "factores": factores,
                        "total": total,
                        "def_map": def_map,
                    },
                )

            # CALCULAR
            if action == "calcular":
                messages.info(
                    request, "✅ Cálculo realizado. Revisa y pulsa Guardar para persistir."
                )
                return render(
                    request,
                    "calificaciones_edit.html",
                    {
                        "calif": calif,
                        "montos_form": montos_form,
                        "factores": factores,
                        "total": total,
                        "def_map": def_map,
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
                calif.usuario = request.user
                calif.save(update_fields=["usuario"])

                messages.success(
                    request, 
                    "✅ Calificación COMPLETADA. Montos y factores guardados correctamente."
                )
                return redirect("main")

        return render(
            request,
            "calificaciones_edit.html",
            {"calif": calif, "montos_form": montos_form, "def_map": def_map},
        )

    # GET
    montos_form = MontosForm(initial=initial, factor_defs=def_map)
    
    # Advertencia si no tiene factores guardados
    if not calif.factores.exists():
        messages.warning(
            request,
            "⚠️ Esta calificación está INCOMPLETA. Debes ingresar y guardar los montos o cancelar para eliminarla."
        )
    
    return render(
        request,
        "calificaciones_edit.html",
        {"calif": calif, "montos_form": montos_form, "def_map": def_map},
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
@login_required(login_url="login")
def sandbox_view(request):
    """
    Pantalla simple para probar el flujo CRUD real (no maqueta).
    """
    return render(request, "sandbox.html")


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