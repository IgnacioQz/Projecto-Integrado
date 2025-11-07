from decimal import Decimal
from django import forms
from .models import TblCalificacion, TblMercado

# =============================================================================
# Constantes y configuración
# =============================================================================
FORM_CONTROL_CLASS = "form-control-modal"
FORM_SELECT_CLASS = "form-select-modal"
DECIMAL_WIDGET_ATTRS = {
    "step": "0.01",
    "class": f"{FORM_CONTROL_CLASS} form-control-sm",
    "placeholder": "0.00"
}

# =============================================================================
# Formulario Paso 1: Datos básicos de calificación
# =============================================================================
class CalificacionBasicaForm(forms.ModelForm):
    """Formulario para crear/editar datos básicos de una calificación."""
    
    # Define el campo mercado explícitamente para personalizar el queryset
    mercado = forms.ModelChoiceField(
        queryset=TblMercado.objects.filter(activo=True).order_by('nombre'),
        widget=forms.Select(attrs={'class': 'form-control'}),
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
            # Cambia el widget de mercado a Select
            "mercado": forms.Select(attrs={"class": FORM_CONTROL_CLASS}),
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
                "type": "date"
            }),
            "secuencia_evento": forms.NumberInput(attrs={
                "class": FORM_CONTROL_CLASS,
            }),
            "dividendo": forms.NumberInput(attrs={
                "class": FORM_CONTROL_CLASS,
                "step": "0.01"
            }),
            "valor_historico": forms.NumberInput(attrs={
                "class": FORM_CONTROL_CLASS,
                "step": "0.01"
            }),
            "factor_actualizacion": forms.NumberInput(attrs={
                "class": FORM_CONTROL_CLASS,
                "step": "0.0001"
            }),
            "ejercicio": forms.NumberInput(attrs={
                "class": FORM_CONTROL_CLASS,
                "placeholder": "Año"
            }),
            "isfut": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "tipo_ingreso": forms.Select(attrs={"class": FORM_SELECT_CLASS}),
        }

# =============================================================================
# Formulario Paso 2: Montos por posición
# =============================================================================
class MontosForm(forms.Form):
    """
    Formulario para ingresar montos en posiciones 8-37.
    
    Args:
        factor_defs (dict): Mapeo {posicion: TblFactorDef} para labels dinámicos
    
    Fields:
        monto_8 hasta monto_37: Campos decimales para cada posición
        
    Methods:
        total_8_19(): Calcula suma de montos en posiciones 8-19
    """
    
    def __init__(self, *args, factor_defs=None, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Crear campos dinámicamente para posiciones 8-37
        for pos in range(8, 38):
            field_name = f"monto_{pos}"
            
            # Configurar campo decimal
            self.fields[field_name] = forms.DecimalField(
                required=False,
                min_value=Decimal("0"),
                max_digits=16, 
                decimal_places=2,
                widget=forms.NumberInput(attrs=DECIMAL_WIDGET_ATTRS),
            )
            
            # Asignar label y help_text desde catálogo si existe
            etiqueta = f"Posición {pos}"
            if factor_defs and pos in factor_defs:
                factor = factor_defs[pos]
                etiqueta = f"{pos} — {factor.nombre}"
                if factor.descripcion:
                    self.fields[field_name].help_text = factor.descripcion
                    
            self.fields[field_name].label = etiqueta

    def total_8_19(self) -> Decimal:
        """Calcula la suma de los montos en posiciones 8-19"""
        return sum(
            (self.cleaned_data.get(f"monto_{pos}") or Decimal("0"))
            for pos in range(8, 20)
        )