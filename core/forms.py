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
        labels = {"instrumento_text": "Instrumento"}

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
                max_digits=16, decimal_places=2,
                widget=forms.NumberInput(attrs={"step": "0.01", "class": "form-control form-control-sm"}),
            )
            # Etiqueta con nombre del catálogo
            etiqueta = f"{pos}"
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
