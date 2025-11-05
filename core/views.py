# core/views.py
from decimal import Decimal, ROUND_HALF_UP

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.db import transaction
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
    Home privado post-login. Desde aquí navegas al sandbox/listado/ingreso.
    """
    return render(request, "main.html")


def logout_view(request):
    """Cierra sesión y vuelve a la portada."""
    logout(request)
    return redirect("welcome")


# =============================================================================
# Mockups 
# =============================================================================
@login_required(login_url="login")
@transaction.atomic
def carga_manual_view(request):
    """
    PASO 1: Crear calificación (datos básicos).
    Migración de funcionalidad desde calificacion_create al mockup cargaManual.html
    
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
                "Calificación creada exitosamente. Continúa con los montos por factor."
            )
            # Redirige al PASO 2 (edición de montos 8..37)
            return redirect("calificacion_edit", pk=calif.pk)

        # Form inválido -> re-render con errores
        messages.error(request, "Por favor corrige los errores en el formulario.")
        return render(request, "cargaManual.html", {"form": form})

    # GET - Mostrar formulario vacío
    form = CalificacionBasicaForm()
    return render(request, "cargaManual.html", {"form": form})


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


@login_required(login_url="login")
@transaction.atomic
def calificacion_edit(request, pk: int):
    """
    PASO 2: Ingreso/edición de montos (pos. 8..37), cálculo de factores y guardado.

    Flujo:
      - GET: muestra el formulario con montos ya guardados (si existen).
      - POST 'calcular': calcula factores y los muestra sin persistir.
      - POST 'guardar': calcula y persiste (upsert) montos y factores.
    Reglas:
      - Denominador = SUMA(montos 8..19)
      - factor_i = monto_i / SUMA(8..19), redondeado a 8 decimales (HALF_UP)
      - Validación: suma(factores 8..19) ≤ 1.00000000
    """

    # 1) Trae la calificación (404 si no existe)
    calif = get_object_or_404(TblCalificacion, pk=pk)

    # 2) Trae el catálogo de definiciones de factores (8..37) activo
    #    y crea un diccionario {posicion: TblFactorDef} para lookup rápido.
    defs_qs = (
        TblFactorDef.objects
        .filter(posicion__gte=8, posicion__lte=37, activo=True)
        .order_by("posicion")
    )
    def_map = {d.posicion: d for d in defs_qs}

    # 3) Carga inicial de montos si ya hay registros guardados
    initial = {
        f"monto_{fv.posicion}": fv.monto_base
        for fv in calif.factores.filter(posicion__gte=8, posicion__lte=37)
    }

    if request.method == "POST":
        # 4) Construye el form con los datos del POST y el catálogo
        montos_form = MontosForm(request.POST, factor_defs=def_map)

        # 'calcular' -> solo mostrar resultados; 'guardar' -> persistir
        action = request.POST.get("action")

        if montos_form.is_valid():
            # 5) Denominador: suma de montos 8..19
            total = montos_form.total_8_19()
            if total <= 0:
                messages.error(request, "Ingresa al menos un monto > 0 entre 8 y 19.")
                return render(
                    request,
                    "calificaciones_edit.html",
                    {"calif": calif, "montos_form": montos_form, "def_map": def_map},
                )

            # 6) Calcula factores para 8..37 y arma estructura amigable para la vista
            #    factores = { pos: {"monto": Decimal, "factor": Decimal, "nombre": str} }
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

            # 7) Regla: la suma de factores 8..19 (ya redondeados) no puede superar 1
            if suma_8_19 > Decimal("1.00000000"):
                messages.error(
                    request,
                    f"La suma de factores 8..19 = {suma_8_19} supera 1.00000000.",
                )
                return render(
                    request,
                    "calificaciones_edit.html",
                    {
                        "calif": calif,
                        "montos_form": montos_form,
                        "factores": factores,   # para mostrar tabla de resultados
                        "total": total,
                        "def_map": def_map,
                    },
                )

            # 8) Acción: CALCULAR -> muestra resultados sin guardar
            if action == "calcular":
                messages.info(
                    request, "Cálculo realizado. Revisa y pulsa Guardar para persistir."
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

            # 9) Acción: GUARDAR -> upsert sobre cada posición 8..37 y registra usuario
            if action == "guardar":
                for pos, row in factores.items():
                    TblFactorValor.objects.update_or_create(
                        calificacion=calif,
                        posicion=pos,
                        defaults={
                            "monto_base": row["monto"],
                            "valor": row["factor"],
                            # si implementaste el FK automático en save(), no necesitas setear factor_def aquí
                            # "factor_def": def_map.get(pos),  # <- opcional si quieres fijarlo explícitamente
                        },
                    )
                # trazabilidad: último usuario que modificó esta calificación
                calif.usuario = request.user
                calif.save(update_fields=["usuario"])

                messages.success(request, "Montos y factores guardados correctamente.")
                return redirect("calificacion_list")

        # 10) Form inválido -> re-render con errores
        return render(
            request,
            "calificaciones_edit.html",
            {"calif": calif, "montos_form": montos_form, "def_map": def_map},
        )

    # 11) GET -> render con inicial; pasamos def_map para que el form ponga labels “pos — nombre”
    montos_form = MontosForm(initial=initial, factor_defs=def_map)
    return render(
        request,
        "calificaciones_edit.html",
        {"calif": calif, "montos_form": montos_form, "def_map": def_map},
    )