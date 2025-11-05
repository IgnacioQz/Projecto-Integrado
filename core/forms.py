from decimal import Decimal
from django import forms
from .models import TblCalificacion

class CalificacionBasicaForm(forms.ModelForm):
    """Paso 1: datos básicos de la calificación.
       OJO: el corredor escribe el instrumento en 'instrumento_text'."""
    
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
            "mercado": forms.TextInput(attrs={
                "class": "form-control-modal",
            }),
            "instrumento_text": forms.TextInput(attrs={
                "class": "form-control-modal",
                "placeholder": "Ej: ACCIÓN, BONO, etc."
            }),
            "descripcion": forms.Textarea(attrs={
                "class": "form-control-modal",
                "rows": 3,
                "placeholder": "Descripción del instrumento"
            }),
            "fecha_pago_dividendo": forms.DateInput(attrs={
                "class": "form-control-modal",
                "type": "date"
            }),
            "secuencia_evento": forms.NumberInput(attrs={
                "class": "form-control-modal",
            }),
            "dividendo": forms.NumberInput(attrs={
                "class": "form-control-modal",
                "step": "0.01"
            }),
            "valor_historico": forms.NumberInput(attrs={
                "class": "form-control-modal",
                "step": "0.01"
            }),
            "factor_actualizacion": forms.NumberInput(attrs={
                "class": "form-control-modal",
                "step": "0.0001"
            }),
            "ejercicio": forms.NumberInput(attrs={
                "class": "form-control-modal",
                "placeholder": "Año"
            }),
            "isfut": forms.CheckboxInput(attrs={
                "class": "form-check-input",
            }),
            "tipo_ingreso": forms.Select(attrs={
                "class": "form-select-modal",
            }),
        }


class MontosForm(forms.Form):
    """
    Form para ingresar montos por posición 8..37.
    Recibe factor_defs={posicion: TblFactorDef} para etiquetar dinámicamente.
    """
    def __init__(self, *args, factor_defs=None, **kwargs):
        super().__init__(*args, **kwargs)

        for pos in range(8, 38):
            self.fields[f"monto_{pos}"] = forms.DecimalField(
                required=False,
                min_value=Decimal("0"),
                max_digits=16, 
                decimal_places=2,
                widget=forms.NumberInput(attrs={
                    "step": "0.01", 
                    "class": "form-control-modal form-control-sm",  
                    "placeholder": "0.00"
                }),
            )
            # Etiqueta con nombre del catálogo
            etiqueta = f"Posición {pos}"
            if factor_defs and pos in factor_defs:
                etiqueta = f"{pos} — {factor_defs[pos].nombre}"
            self.fields[f"monto_{pos}"].label = etiqueta
            
            # (opcional) ayuda visible bajo el input
            if factor_defs and pos in factor_defs and factor_defs[pos].descripcion:
                self.fields[f"monto_{pos}"].help_text = factor_defs[pos].descripcion

    def total_8_19(self):
        total = Decimal("0")
        for pos in range(8, 20):
            v = self.cleaned_data.get(f"monto_{pos}")
            if v:
                total += v
        return total