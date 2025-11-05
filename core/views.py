# core/views.py
from decimal import Decimal, ROUND_HALF_UP

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.db import models,transaction
from django.shortcuts import render, redirect, get_object_or_404
from .models import TblFactorDef

from .models import TblCalificacion, TblFactorValor
from .forms import CalificacionBasicaForm, MontosForm


# =============================================================================
# Utilidad de redondeo
# -----------------------------------------------------------------------------
# Redondea con 8 decimales usando HALF_UP (la regla de negocio pedida)
# =============================================================================
def _round8(x: Decimal) -> Decimal:
    return x.quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP)


# =============================================================================
# Páginas base / autenticación
# =============================================================================
def welcome_view(request):
    """Portada pública (antes de iniciar sesión)."""
    return render(request, "welcome.html")


def login_view(request):
    """
    Login clásico con el backend de Django.

    GET  -> muestra el form de login
    POST -> autentica credenciales y crea la sesión con `login(...)`
    """
    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "").strip()

        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)              # crea cookie de sesión
            return redirect("main")
        messages.error(request, "Usuario o contraseña incorrectos.")
    return render(request, "login.html")


@login_required(login_url="login")
def main_view(request):
    """
    Vista principal del sistema con listado completo de calificaciones.
    Muestra tabla con todos los campos y factores (8-37).
    """
    # Obtener calificaciones con relaciones optimizadas
    items = (
        TblCalificacion.objects
        .select_related('tipo_ingreso', 'instrumento')
        .prefetch_related('factores')
        .order_by('-fecha_creacion')[:200]
    )
    
    # Preparar diccionario de factores por calificación
    for item in items:
        # Acceder a factores precargados
        all_factores = list(item.factores.all())
        
        # DEBUG: Imprimir en consola para verificar
        print(f"Calificación {item.calificacion_id}:")
        print(f"  Total factores: {len(all_factores)}")
        for f in all_factores:
            print(f"    Posición {f.posicion}: {f.valor}")
        
        # Crear diccionario para el template con valores redondeados
        item.factores_dict = {
            f.posicion: _round8(f.valor)
            for f in all_factores
            if 8 <= f.posicion <= 37
        }
        print(f"  factores_dict: {item.factores_dict}")
    
    return render(request, "main.html", {"items": items})


def logout_view(request):
    """Cierra sesión y vuelve a la portada."""
    logout(request)
    return redirect("welcome")


# =============================================================================
# Mockups 
# =============================================================================
# Actualiza estas dos vistas en views.py:

@login_required(login_url="login")
@transaction.atomic
def carga_manual_view(request):
    """
    PASO 1: Crear calificación (datos básicos).
    IMPORTANTE: La calificación se crea pero NO se considera completa hasta 
    que se ingresen los montos en el PASO 2.
    """
    if request.method == "POST":
        form = CalificacionBasicaForm(request.POST)
        if form.is_valid():
            calif = form.save(commit=False)
            calif.usuario = request.user
            calif.save()

            messages.warning(
                request,
                "⚠️ Calificación creada PARCIALMENTE. Debes completar los montos (PASO 2) para que sea válida."
            )
            # Redirige OBLIGATORIAMENTE al PASO 2
            return redirect("calificacion_edit", pk=calif.pk)

        messages.error(request, "Por favor corrige los errores en el formulario.")
        return render(request, "cargaManual.html", {"form": form})

    # GET
    form = CalificacionBasicaForm()
    return render(request, "cargaManual.html", {"form": form})


@login_required(login_url="login")
@transaction.atomic
def calificacion_edit(request, pk: int):
    """
    PASO 2: Ingreso/edición de montos (pos. 8..37), cálculo y guardado.
    Si el usuario cancela o vuelve atrás sin guardar, la calificación queda incompleta.
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

def carga_masiva_view(request):
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


