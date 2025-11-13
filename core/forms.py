# =============================================================================
# forms.py — Formularios del Mantenedor de Calificaciones
# =============================================================================
# Contiene:
# 1) Config global de widgets/clases
# 2) CalificacionBasicaForm (paso 1)
# 3) MontosForm (paso 2A - montos 8..37)
# 4) FactoresForm (paso 2B - factores 8..37)
# -----------------------------------------------------------------------------

# =============================================================================
# IMPORTS
# =============================================================================
from decimal import Decimal, ROUND_HALF_UP
from django import forms
from django.utils import timezone

from .models import TblCalificacion, TblMercado


# =============================================================================
# CONSTANTES (evitan “números mágicos”)
# =============================================================================
POS_MIN = 8
POS_BASE_MAX = 19     # sumatoria base (8..19)
POS_MAX = 37

FORM_CONTROL_CLASS = "form-control-modal"
FORM_SELECT_CLASS = "form-select-modal"
DECIMAL_WIDGET_ATTRS = {
    "step": "0.01",
    "class": f"{FORM_CONTROL_CLASS} form-control-sm",
    "placeholder": "0.00",
}


# =============================================================================
# HELPERS ( utilidades para campos/validaciones)
# =============================================================================
def _q8(x: Decimal) -> Decimal:
    """Redondea a 8 decimales con HALF_UP."""
    return (x or Decimal("0")).quantize(Decimal("0.00000000"), rounding=ROUND_HALF_UP)


# =============================================================================
# FORMULARIO PASO 1: DATOS BÁSICOS DE CALIFICACIÓN
# =============================================================================
class CalificacionBasicaForm(forms.ModelForm):
    """
    Form para crear/editar los datos base de la calificación.
    - Ajusta el 'max' de fecha a hoy.
    - Valida campos numéricos y rangos simples.
    """

    # Campo mercado personalizado (solo activos)
    mercado = forms.ModelChoiceField(
        queryset=TblMercado.objects.filter(activo=True).order_by("nombre"),
        widget=forms.Select(attrs={"class": FORM_SELECT_CLASS}),
        empty_label="Seleccione un mercado",
    )

    class Meta:
        model = TblCalificacion
        fields = [
            "mercado", "instrumento_text", "descripcion",
            "fecha_pago_dividendo", "secuencia_evento",
            "dividendo", "valor_historico",
            "factor_actualizacion", "ejercicio", "isfut",
            "tipo_ingreso",
        ]
        labels = {
            "instrumento_text": "Instrumento",
            "mercado": "Mercado",
            "descripcion": "Descripción",
            "fecha_pago_dividendo": "Fecha Pago Dividendo",
            "secuencia_evento": "Secuencia Evento",
            "dividendo": "Dividendo",
            "valor_historico": "Valor Histórico",
            "factor_actualizacion": "Factor Actualización",
            "ejercicio": "Ejercicio",
            "isfut": "ISFUT",
            "tipo_ingreso": "Tipo de Ingreso",
        }
        widgets = {
            "mercado": forms.Select(attrs={"class": FORM_SELECT_CLASS}),
            "instrumento_text": forms.TextInput(attrs={
                "class": FORM_CONTROL_CLASS,
                "placeholder": "Ej: ACCIÓN, BONO, etc."
            }),
            "descripcion": forms.Textarea(attrs={
                "class": FORM_CONTROL_CLASS,
                "rows": 3,
                "placeholder": "Descripción del instrumento"
            }),
            "fecha_pago_dividendo": forms.DateInput(attrs={
                "class": FORM_CONTROL_CLASS,
                "type": "date",
                "min": "1980-01-01",
            }),
            "secuencia_evento": forms.NumberInput(attrs={"class": FORM_CONTROL_CLASS}),
            "dividendo": forms.NumberInput(attrs={"class": FORM_CONTROL_CLASS, "step": "0.01"}),
            "valor_historico": forms.NumberInput(attrs={"class": FORM_CONTROL_CLASS, "step": "0.01"}),
            "factor_actualizacion": forms.NumberInput(attrs={"class": FORM_CONTROL_CLASS, "step": "0.0001"}),
            "ejercicio": forms.NumberInput(attrs={"class": FORM_CONTROL_CLASS, "placeholder": "Año"}),
            "isfut": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "tipo_ingreso": forms.Select(attrs={"class": FORM_SELECT_CLASS}),
        }

    def __init__(self, *args, **kwargs):
        """Configura el tope de fecha a 'hoy'."""
        super().__init__(*args, **kwargs)
        hoy = timezone.localdate().isoformat()  # 'YYYY-MM-DD'
        self.fields["fecha_pago_dividendo"].widget.attrs["max"] = hoy

    # --- Validaciones simples y legibles ---
    def clean_instrumento_text(self):
        inst = (self.cleaned_data.get("instrumento_text") or "").strip()
        if not inst:
            raise forms.ValidationError("El campo 'Instrumento' no puede estar vacío.")
        return inst

    def clean_fecha_pago_dividendo(self):
        fecha = self.cleaned_data.get("fecha_pago_dividendo")
        if not fecha:
            return fecha
        if fecha > timezone.localdate():
            raise forms.ValidationError("La fecha de pago no puede ser futura.")
        return fecha

    def clean_secuencia_evento(self):
        v = self.cleaned_data.get("secuencia_evento")
        if v is not None and v < 0:
            raise forms.ValidationError("La secuencia del evento no puede ser negativa.")
        return v

    def clean_dividendo(self):
        v = self.cleaned_data.get("dividendo")
        if v is not None and v < 0:
            raise forms.ValidationError("El dividendo no puede ser negativo.")
        return v

    def clean_valor_historico(self):
        v = self.cleaned_data.get("valor_historico")
        if v is not None and v < 0:
            raise forms.ValidationError("El valor histórico no puede ser negativo.")
        return v

    def clean_factor_actualizacion(self):
        v = self.cleaned_data.get("factor_actualizacion")
        if v is not None and v <= 0:
            raise forms.ValidationError("El factor de actualización debe ser mayor a cero.")
        return v

    def clean_ejercicio(self):
        v = self.cleaned_data.get("ejercicio")
        if v is not None:
            año_actual = timezone.localdate().year
            if v < 1980 or v > año_actual:
                raise forms.ValidationError(f"El ejercicio debe estar entre 1980 y {año_actual}.")
        return v

    def clean_descripcion(self):
        v = (self.cleaned_data.get("descripcion") or "").strip()
        if len(v) > 300:
            raise forms.ValidationError("La descripción no puede exceder los 300 caracteres.")
        return v


# =============================================================================
# FORMULARIO PASO 2-A: INGRESO DE MONTOS (8..37)
# =============================================================================
class MontosForm(forms.Form):
    """
    Ingreso de montos para posiciones 8..37.
    - Crea dinámicamente campos Decimal (2 decimales).
    - Usa labels y help_text desde el catálogo (factor_defs).
    """

    def __init__(self, *args, factor_defs=None, **kwargs):
        super().__init__(*args, **kwargs)

        for pos in range(POS_MIN, POS_MAX + 1):
            field_name = f"monto_{pos}"

            # Campo decimal simple (2 decimales)
            self.fields[field_name] = forms.DecimalField(
                required=False,
                min_value=Decimal("0"),
                max_digits=16,
                decimal_places=2,
                widget=forms.NumberInput(attrs=DECIMAL_WIDGET_ATTRS),
            )

            # Etiqueta/ayuda desde catálogo (si existe definición)
            label = f"Posición {pos}"
            if factor_defs and pos in factor_defs:
                fdef = factor_defs[pos]
                label = f"{pos} — {fdef.nombre}"
                if getattr(fdef, "descripcion", None):
                    self.fields[field_name].help_text = fdef.descripcion

            self.fields[field_name].label = label

    def total_8_19(self) -> Decimal:
        """Suma los montos en posiciones 8..19 (base)."""
        return sum(
            (self.cleaned_data.get(f"monto_{pos}") or Decimal("0") for pos in range(POS_MIN, POS_BASE_MAX + 1)),
            Decimal("0"),
        )


# =============================================================================
# FORMULARIO PASO 2-B: INGRESO DE FACTORES (8..37)
# =============================================================================
class FactoresForm(forms.Form):
    """
    Ingreso MANUAL de factores para posiciones 8..37.
    Reglas:
      - Cada campo: hasta 8 decimales (0..1).
      - Suma 8..19 <= 1.0 y al menos un factor > 0 en 8..19.
    """

    def __init__(self, *args, factor_defs=None, **kwargs):
        super().__init__(*args, **kwargs)
        if not factor_defs:
            return  # sin catálogo no generamos campos

        for pos in range(POS_MIN, POS_MAX + 1):
            if pos not in factor_defs:
                continue

            fdef = factor_defs[pos]
            field_name = f"factor_{pos}"

            self.fields[field_name] = forms.DecimalField(
                label=f"{pos:02d} — {fdef.nombre}",
                required=False,
                max_digits=9,            # 1 entero + 8 decimales
                decimal_places=8,
                initial=Decimal("0.00000000"),
                widget=forms.NumberInput(attrs={
                    "class": "form-control form-control-sm",
                    "step": "0.00000001",
                    "min": "0",
                    "max": "1",
                    "placeholder": "0.00000000",
                }),
                help_text=getattr(fdef, "descripcion", None),
            )

            # Validador por-campo (negativos y > 1 no permitidos, y redondeo a 8 decimales)
            def make_clean(fname):
                def _clean(self):
                    v = self.cleaned_data.get(fname)
                    if v is None:
                        return Decimal("0.00000000")
                    if v < 0:
                        raise forms.ValidationError("El factor no puede ser negativo.")
                    if v > 1:
                        raise forms.ValidationError("El factor no puede ser mayor a 1.")
                    return _q8(v)
                return _clean

            setattr(self, f"clean_{field_name}", make_clean(field_name).__get__(self, type(self)))

    # --- Validación transversal del formulario ---
    def clean(self):
        """
        Reglas globales:
          - suma(8..19) <= 1.0
          - al menos un factor > 0 en 8..19
        """
        cleaned = super().clean()

        suma_8_19 = Decimal("0")
        tiene_alguno = False

        for pos in range(POS_MIN, POS_BASE_MAX + 1):
            v = cleaned.get(f"factor_{pos}") or Decimal("0")
            suma_8_19 += v
            if v > 0:
                tiene_alguno = True

        if suma_8_19 > Decimal("1.00000000"):
            raise forms.ValidationError(
                f"La suma de factores 8-19 ({_q8(suma_8_19)}) excede 1.00000000. Ajusta los valores."
            )
        if not tiene_alguno:
            raise forms.ValidationError(
                "Debes ingresar al menos un factor mayor a 0 en las posiciones 8-19."
            )

        return cleaned
