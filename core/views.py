# core/views.py
# =============================================================================
# IMPORTACIONES
# =============================================================================
from decimal import Decimal, ROUND_HALF_UP
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.auth.models import User, Group
from django.db import transaction
from django.shortcuts import render, redirect, get_object_or_404
from django.db.models import Prefetch


from .models import (
    TblCalificacion, TblFactorValor, TblFactorDef,
    TblTipoIngreso, TblMercado
)
from .forms import CalificacionBasicaForm, MontosForm, FactoresForm


# =============================================================================
# CONSTANTES DE DOMINIO (evitan “números mágicos”)
# =============================================================================
POS_MIN = 8
POS_BASE_MAX = 19   # para sumatoria base (8..19)
POS_MAX = 37
FACTOR_MAX_SUM = Decimal("1.00000000")


# =============================================================================
# UTILIDADES (rounding, grupos, redirects)
# =============================================================================
def _round8(x: Decimal) -> Decimal:
    """Redondea a 8 decimales (ROUND_HALF_UP)."""
    return x.quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP)


def _in_group(user, group_name: str) -> bool:
    """Verifica si un usuario pertenece a un grupo."""
    return user.groups.filter(name=group_name).exists()


def _redirect_after_login(user):
    """Destino único tras login: Admin → dashboard, otros → main."""
    if user.is_superuser or _in_group(user, "Administrador"):
        return redirect("dashboard")
    return redirect("main")


# =============================================================================
# HELPERS DE NEGOCIO (factores/montos)
# =============================================================================
def _build_def_map():
    """Catálogo {pos: TblFactorDef} sólo para posiciones 8..37 activas."""
    defs_qs = (
        TblFactorDef.objects
        .filter(posicion__gte=POS_MIN, posicion__lte=POS_MAX, activo=True)
        .order_by("posicion")
    )
    return {d.posicion: d for d in defs_qs}


def _initial_data(calif: TblCalificacion):
    """Construye initial data para formularios de montos y factores."""
    qs = calif.factores.filter(posicion__gte=POS_MIN, posicion__lte=POS_MAX)
    initial_montos = {f"monto_{fv.posicion}": fv.monto_base for fv in qs}
    initial_factores = {f"factor_{fv.posicion}": fv.valor for fv in qs}
    return initial_montos, initial_factores


def _calc_factores_desde_montos(montos_form, def_map):
    """
    A partir de los montos (8..37) calcula factores proporcionales a total (8..19).
    Devuelve: (factores_dict, total_base, suma_8_19)
    """
    total = montos_form.total_8_19()
    factores = {}
    suma_8_19 = Decimal("0")

    # Evita división por cero más adelante
    for pos in range(POS_MIN, POS_MAX + 1):
        monto = montos_form.cleaned_data.get(f"monto_{pos}") or Decimal("0")
        factor = _round8(monto / total) if total > 0 else Decimal("0")
        nombre = def_map[pos].nombre if pos in def_map else str(pos)
        factores[pos] = {"monto": monto, "factor": factor, "nombre": nombre}
        if POS_MIN <= pos <= POS_BASE_MAX:
            suma_8_19 += factor

    return factores, total, suma_8_19


def _collect_factores_desde_form(factores_form, def_map):
    """
    Recolecta factores manuales (8..37) desde el form.
    Devuelve: (factores_dict, suma_8_19)
    """
    factores = {}
    suma_8_19 = Decimal("0")

    for pos in range(POS_MIN, POS_MAX + 1):
        factor = factores_form.cleaned_data.get(f"factor_{pos}") or Decimal("0")
        nombre = def_map[pos].nombre if pos in def_map else str(pos)
        factores[pos] = {"factor": factor, "nombre": nombre}
        if POS_MIN <= pos <= POS_BASE_MAX:
            suma_8_19 += factor

    return factores, suma_8_19


# =============================================================================
# DASHBOARD / HOME
# =============================================================================
@login_required(login_url="login")
def dashboard(request):
    """
    Dashboard solo para administradores. Otros roles van al mantenedor.
    """
    user = request.user
    if user.is_superuser or _in_group(user, "Administrador"):
         # Métricas básicas
        total_calificaciones = TblCalificacion.objects.count()
        ultimas = TblCalificacion.objects.order_by("-fecha_creacion")[:5]

        # Métricas de usuarios (para tarjetas)
        usuarios_total = User.objects.count()
        try:
            g_admin = Group.objects.get(name="Administrador")
            g_cor = Group.objects.get(name="Corredor")
            g_ana = Group.objects.get(name="AnalistaTributario")
            usuarios_por_grupo = {
                "Administrador": g_admin.user_set.count(),
                "Corredor": g_cor.user_set.count(),
                "AnalistaTributario": g_ana.user_set.count(),
            }
        except Group.DoesNotExist:
            usuarios_por_grupo = {}

        context = {
            "total_calificaciones": total_calificaciones,
            "ultimas_calificaciones": ultimas,
            "usuarios_total": usuarios_total,
            "usuarios_por_grupo": usuarios_por_grupo,
            "es_admin": True,  # flag para template
        }
        return render(request, "dashboards/admin.html", context)
    return redirect("main")

@login_required(login_url="login")
def auditoria_list(request):
    """
    Placeholder de Auditoría (visible solo para Admin/superusuario).
    Cuando tengas el modelo de auditoría, cámbialo por un ListView real.
    """
    user = request.user
    if not (user.is_superuser or user.groups.filter(name="Administrador").exists()):
        messages.error(request, "No tienes permisos para ver Auditoría.")
        return redirect("main")

    # TODO: Reemplazar con consulta real cuando exista el modelo AuditLog
    auditorias = []  # lista vacía por ahora

    return render(request, "auditoria/lista_log.html", {
        "auditorias": auditorias,
        "es_admin": True,
    })

# =============================================================================
# AUTENTICACIÓN
# =============================================================================
def welcome_view(request):
    return render(request, "welcome.html")


def login_view(request):
    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "").strip()
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            return _redirect_after_login(user)
        messages.error(request, "Usuario o contraseña incorrectos.")
    return render(request, "login.html")


def logout_view(request):
    logout(request)
    return redirect("welcome")


# =============================================================================
# VISTA PRINCIPAL - LISTADO Y FILTROS
# =============================================================================
@login_required(login_url="login")
def main_view(request):
    filtro_mercado = request.GET.get("mercado", "")
    filtro_tipo_ingreso = request.GET.get("tipo_ingreso", "")
    filtro_ejercicio = request.GET.get("ejercicio", "")


    qs = (
        TblCalificacion.objects
        .select_related("mercado", "tipo_ingreso")
        .prefetch_related("factores")
    )

    if filtro_mercado:
        qs = qs.filter(mercado_id=filtro_mercado)
    if filtro_tipo_ingreso:
        qs = qs.filter(tipo_ingreso_id=filtro_tipo_ingreso)
    if filtro_ejercicio:
        try:
            qs = qs.filter(ejercicio=int(filtro_ejercicio))
        except ValueError:
            pass

    items = qs.order_by("-fecha_creacion")[:500]

    # Prepara estructuras de factores para la tabla
    for it in items:
        try:
            factor_qs = it.factores.all()
        except Exception:
            factor_qs = it.tblfactorvalor_set.all()

        factores_map = {int(f.posicion): f.valor for f in factor_qs}
        it.factores_map = factores_map
        it.factores_array = [factores_map.get(pos) for pos in range(POS_MIN, POS_MAX + 1)]

    context = {
        "items": items,
        "mercados_disponibles": TblMercado.objects.filter(activo=True).order_by("nombre"),
        "tipos_ingreso_disponibles": TblTipoIngreso.objects.all().order_by("nombre_tipo_ingreso"),
        "ejercicios_disponibles": (
            TblCalificacion.objects.values_list("ejercicio", flat=True)
            .distinct()
            .order_by("-ejercicio")
        ),
        "filtro_mercado": filtro_mercado,
        "filtro_tipo_ingreso": filtro_tipo_ingreso,
        "filtro_ejercicio": filtro_ejercicio,
        "es_analista": _in_group(request.user, "AnalistaTributario"),
    }
    return render(request, "calificaciones/list.html", context)


# =============================================================================
# CALIFICACIONES - CARGA MANUAL (PASO 1)  **ÚNICO PUNTO DE CREACIÓN**
# =============================================================================
@login_required(login_url="login")
@permission_required("core.add_tblcalificacion", raise_exception=True)
def carga_manual_view(request):
    """
    PASO 1: Crear nueva calificación manualmente.
    (Este es el único punto de creación; otras rutas delegan aquí.)
    """
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

    mercados = TblMercado.objects.filter(activo=True).order_by("nombre")
    return render(request, "calificaciones/form_inicial.html", {"form": form, "mercados": mercados})


# (Compatibilidad) Si en tu proyecto existe la URL a calificacion_create,
# ahora simplemente delega a carga_manual_view para evitar duplicar lógica.
@login_required(login_url="login")
@permission_required("core.add_tblcalificacion", raise_exception=True)
def calificacion_create(request):
    return carga_manual_view(request)


# =============================================================================
# CALIFICACIONES - EDICIÓN (PASO 2)
# =============================================================================
@login_required(login_url="login")
@permission_required("core.change_tblcalificacion", raise_exception=True)
def calificacion_edit(request, pk: int):
    """
    PASO 2: Edición de montos y factores (modo montos o manual).
    """
    calif = get_object_or_404(TblCalificacion, pk=pk)
    def_map = _build_def_map()
    initial_montos, initial_factores = _initial_data(calif)
    modo_ingreso = request.POST.get("modo_ingreso", request.GET.get("modo_ingreso", "montos"))

    # -------------------------------------------------------------------------
    # POST
    # -------------------------------------------------------------------------
    if request.method == "POST":
        action = request.POST.get("action")

        # Eliminar calificación
        if action == "eliminar":
            calif_id = calif.calificacion_id
            calif.delete()
            messages.success(request, f"🗑️ Calificación #{calif_id} eliminada permanentemente.")
            return redirect("main")

        # Cancelar sin guardar
        if action == "cancelar":
            messages.info(request, "Edición cancelada. No se guardaron cambios.")
            return redirect("main")

        # ----------------------------- MODO MONTOS -----------------------------
        if modo_ingreso == "montos":
            montos_form = MontosForm(request.POST, factor_defs=def_map)
            factores_form = FactoresForm(initial=initial_factores, factor_defs=def_map)

            if montos_form.is_valid():
                factores, total, suma_8_19 = _calc_factores_desde_montos(montos_form, def_map)

                # Validación base: al menos un monto > 0
                if total <= 0:
                    messages.error(request, "❌ Debes ingresar al menos un monto mayor a 0 en las posiciones 8-19.")
                    return render(request, "calificaciones/form_factores.html", {
                        "calif": calif,
                        "montos_form": montos_form,
                        "factores_form": factores_form,
                        "def_map": def_map,
                        "modo_ingreso": modo_ingreso,
                    })

                # Límite de suma
                if suma_8_19 > FACTOR_MAX_SUM:
                    messages.error(request, f"❌ La suma de factores 8-19 = {suma_8_19} supera {FACTOR_MAX_SUM}.")
                    return render(request, "calificaciones/form_factores.html", {
                        "calif": calif,
                        "montos_form": montos_form,
                        "factores_form": factores_form,
                        "factores": factores,
                        "total": total,
                        "suma_factores_8_19": suma_8_19,
                        "suma_valida": False,
                        "def_map": def_map,
                        "modo_ingreso": modo_ingreso,
                    })

                # Acción: calcular
                if action == "calcular":
                    messages.info(request, "✅ Cálculo realizado. Revisa y pulsa Guardar para persistir.")
                    return render(request, "calificaciones/form_factores.html", {
                        "calif": calif,
                        "montos_form": montos_form,
                        "factores_form": factores_form,
                        "factores": factores,
                        "total": total,
                        "suma_factores_8_19": suma_8_19,
                        "suma_valida": True,
                        "def_map": def_map,
                        "modo_ingreso": modo_ingreso,
                    })

                # Acción: guardar
                if action == "guardar":
                    for pos, row in factores.items():
                        TblFactorValor.objects.update_or_create(
                            calificacion=calif,
                            posicion=pos,
                            defaults={
                                "monto_base": row["monto"],
                                "valor": row["factor"],
                                "factor_def": def_map.get(pos),  
                            },
                        )
                    calif.usuario = request.user
                    calif.save(update_fields=["usuario"])
                    messages.success(request, "✅ Calificación guardada correctamente.")
                    return redirect("main")

            # Errores de form
            return render(request, "calificaciones/form_factores.html", {
                "calif": calif,
                "montos_form": montos_form,
                "factores_form": factores_form,
                "def_map": def_map,
                "modo_ingreso": modo_ingreso,
            })

        # --------------------------- MODO FACTORES -----------------------------
        else:  # modo_ingreso == "factores"
            montos_form = MontosForm(initial=initial_montos, factor_defs=def_map)
            factores_form = FactoresForm(request.POST, factor_defs=def_map)

            if factores_form.is_valid():
                factores, suma_8_19 = _collect_factores_desde_form(factores_form, def_map)
                suma_valida = (suma_8_19 <= FACTOR_MAX_SUM)

                # Acción: validar
                if action == "validar":
                    if suma_valida:
                        messages.success(request, f"✅ Validación exitosa. Suma = {suma_8_19}. Pulsa Guardar para persistir.")
                    else:
                        messages.error(request, f"❌ La suma de factores 8-19 = {suma_8_19} supera {FACTOR_MAX_SUM}.")
                    return render(request, "calificaciones/form_factores.html", {
                        "calif": calif,
                        "montos_form": montos_form,
                        "factores_form": factores_form,
                        "factores": factores,
                        "suma_factores_8_19": suma_8_19,
                        "suma_valida": suma_valida,
                        "def_map": def_map,
                        "modo_ingreso": modo_ingreso,
                    })

                # Acción: guardar
                if action == "guardar":
                    if not suma_valida:
                        messages.error(request, "❌ No se puede guardar. La suma de factores 8-19 excede 1.0")
                        return render(request, "calificaciones/form_factores.html", {
                            "calif": calif,
                            "montos_form": montos_form,
                            "factores_form": factores_form,
                            "factores": factores,
                            "suma_factores_8_19": suma_8_19,
                            "suma_valida": suma_valida,
                            "def_map": def_map,
                            "modo_ingreso": modo_ingreso,
                        })

                    for pos, row in factores.items():
                        TblFactorValor.objects.update_or_create(
                            calificacion=calif,
                            posicion=pos,
                            defaults={
                                "monto_base": None,
                                "valor": row["factor"],
                                "factor_def": def_map.get(pos),  # ✅ agregado
                            },
                        )
                    calif.usuario = request.user
                    calif.save(update_fields=["usuario"])
                    messages.success(request, "✅ Factores guardados manualmente.")
                    return redirect("main")

            # Errores de form
            return render(request, "calificaciones/form_factores.html", {
                "calif": calif,
                "montos_form": montos_form,
                "factores_form": factores_form,
                "def_map": def_map,
                "modo_ingreso": modo_ingreso,
            })

    # -------------------------------------------------------------------------
    # GET (carga inicial)
    # -------------------------------------------------------------------------
    montos_form = MontosForm(initial=initial_montos, factor_defs=def_map)
    factores_form = FactoresForm(initial=initial_factores, factor_defs=def_map)

    if not calif.factores.exists():
        messages.warning(request, "⚠️ Calificación incompleta. Debes ingresar montos o factores.")

    return render(request, "calificaciones/form_factores.html", {
        "calif": calif,
        "montos_form": montos_form,
        "factores_form": factores_form,
        "def_map": def_map,
        "modo_ingreso": modo_ingreso,
    })
    # -------------------------------------------------------------------------
    # GET (carga inicial)
    # -------------------------------------------------------------------------
    montos_form = MontosForm(initial=initial_montos, factor_defs=def_map)
    factores_form = FactoresForm(initial=initial_factores, factor_defs=def_map)

    if not calif.factores.exists():
        messages.warning(request, "⚠️ Calificación incompleta. Debes ingresar montos o factores.")

    return render(request, "calificaciones/form_factores.html", {
        "calif": calif,
        "montos_form": montos_form,
        "factores_form": factores_form,
        "def_map": def_map,
        "modo_ingreso": modo_ingreso,
    })


# =============================================================================
# CARGA MASIVA (PENDIENTE)
# =============================================================================
@login_required(login_url="login")
@permission_required("core.add_tblcalificacion", raise_exception=True)
def carga_masiva_view(request):
    return render(request, "calificaciones/carga_masiva.html")


# =============================================================================
# ELIMINACIONES
# =============================================================================


@login_required(login_url="login")
@permission_required("core.delete_tblcalificacion", raise_exception=True)
def calificacion_delete(request):
    if request.method == "POST":
        ids = request.POST.getlist("ids[]")
        if not ids:
            messages.error(request, "❌ No se seleccionaron calificaciones.")
            return redirect("main")

        ids = [int(i) for i in ids]
        calificaciones = TblCalificacion.objects.filter(pk__in=ids)
        count = calificaciones.count()

        if count == 0:
            messages.error(request, "❌ No se encontraron las calificaciones seleccionadas.")
            return redirect("main")

        calificaciones.delete()
        messages.success(
            request,
            f"✅ {count} calificación{'es' if count > 1 else ''} eliminada{'s' if count > 1 else ''}."
        )
        return redirect("main")

    return redirect("main")


# =============================================================================
#  Detalle de califiaciones
# =============================================================================

@login_required(login_url="login")
def calificacion_detalles(request, pk: int):
    """
    Detalle de calificación que muestra el nombre del factor.
    - Toma el nombre desde fv.factor_def.nombre cuando existe
    - Si no, usa el catálogo TblFactorDef por posición (fallback)
    """
    calificacion = (
        TblCalificacion.objects
        .select_related("mercado", "tipo_ingreso")
        .get(pk=pk)
    )

    # Factores 8..37 con su definición (si está enlazada)
    factores_qs = (
        calificacion.factores
        .filter(posicion__gte=8, posicion__lte=37)
        .select_related("factor_def")
        .order_by("posicion")
    )

    # Catálogo por posición para fallback
    def_map = {
        d.posicion: d.nombre
        for d in TblFactorDef.objects.filter(posicion__gte=8, posicion__lte=37, activo=True)
    }

    # Normalizar filas para el template
    factores_rows = []
    for fv in factores_qs:
        nombre = fv.factor_def.nombre if fv.factor_def else def_map.get(fv.posicion, f"Factor {fv.posicion}")
        factores_rows.append({
            "posicion": fv.posicion,
            "nombre": nombre,
            "monto_base": fv.monto_base,
            "valor": fv.valor,
        })

    return render(request, "calificaciones/detalles.html", {
        "calificacion": calificacion,   # usa 'calificacion' en el template
        "factores_rows": factores_rows, # lista lista para iterar
    })