# core/admin.py
from django.contrib import admin
from .models import (
    TblInstrumento,
    TblTipoIngreso,
    TblArchivoFuente,
    TblCalificacion,
    TblFactorValor,
    TblMercado,
    TblFactorDef,
)

# =============================================================================
# Mercado
# =============================================================================
@admin.register(TblMercado)
class MercadoAdmin(admin.ModelAdmin):
    list_display  = ("nombre", "codigo", "activo")
    search_fields = ("nombre",)
    ordering      = ("nombre",)


# =============================================================================
# Instrumento
# =============================================================================
@admin.register(TblInstrumento)
class InstrumentoAdmin(admin.ModelAdmin):
    list_display  = ("instrumento_id", "nombre", "tipo_instrumento")
    search_fields = ("nombre", "tipo_instrumento")


# =============================================================================
# Tipo de Ingreso
# =============================================================================
@admin.register(TblTipoIngreso)
class TipoIngresoAdmin(admin.ModelAdmin):
    list_display = ("tipo_ingreso_id", "nombre_tipo_ingreso", "prioridad")
    ordering     = ("prioridad",)


# =============================================================================
# Archivo Fuente (cargas masivas)
# =============================================================================
@admin.register(TblArchivoFuente)
class ArchivoFuenteAdmin(admin.ModelAdmin):
    list_display  = ("archivo_fuente_id", "nombre_archivo", "ruta_almacenamiento", "fecha_subida", "usuario")
    search_fields = ("nombre_archivo", "ruta_almacenamiento")


# =============================================================================
# Calificación Tributaria
# =============================================================================
@admin.register(TblCalificacion)
class CalificacionAdmin(admin.ModelAdmin):
    list_display  = ("calificacion_id", "ejercicio", "mercado", "instrumento", "secuencia_evento", "fecha_creacion")
    list_filter   = ("ejercicio", "mercado", "instrumento")
    # Nota: el doble guion bajo "__" permite buscar por campo de relación ForeignKey
    search_fields = ("instrumento__nombre",)


# =============================================================================
# Factor Valor (posiciones 8..37)
# =============================================================================
@admin.register(TblFactorValor)
class FactorValorAdmin(admin.ModelAdmin):
    list_display = ("id", "calificacion", "posicion", "valor")
    list_filter  = ("posicion",)


# =============================================================================
# Definición de factores tributarios (posiciones 8..37)
# =============================================================================
@admin.register(TblFactorDef)
class FactorDefAdmin(admin.ModelAdmin):
    list_display  = ("posicion", "nombre", "descripcion")
    search_fields = ("nombre", "descripcion")
