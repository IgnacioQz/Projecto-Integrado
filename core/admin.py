# core/admin.py
from django.contrib import admin
from .models import (
    TblInstrumento, TblTipoIngreso, TblArchivoFuente,
    TblCalificacion, TblFactorValor
)

# ===============================================================
# Admin: Instrumento
# ===============================================================
@admin.register(TblInstrumento)
class InstrumentoAdmin(admin.ModelAdmin):
    # columnas visibles en la tabla del panel admin
    list_display = ("instrumento_id", "nombre", "tipo_instrumento")

    # campos por los que se puede buscar (barra de búsqueda)
    search_fields = ("nombre", "tipo_instrumento")

# ===============================================================
# Admin: Tipo de Ingreso
# ===============================================================
@admin.register(TblTipoIngreso)
class TipoIngresoAdmin(admin.ModelAdmin):
    # columnas visibles
    list_display = ("tipo_ingreso_id", "nombre_tipo_ingreso", "prioridad")

    # define el orden por defecto de las filas
    ordering = ("prioridad",)

# ===============================================================
# Admin: Archivo Fuente (cargas masivas)
# ===============================================================
@admin.register(TblArchivoFuente)
class ArchivoFuenteAdmin(admin.ModelAdmin):
    # columnas que se muestran en la tabla
    list_display = (
        "archivo_fuente_id",
        "nombre_archivo",
        "ruta_almacenamiento",
        "fecha_subida",
        "usuario",
    )

    # activa la búsqueda rápida por nombre o ruta
    search_fields = ("nombre_archivo", "ruta_almacenamiento")

# ===============================================================
# Admin: Calificación Tributaria
# ===============================================================
@admin.register(TblCalificacion)
class CalificacionAdmin(admin.ModelAdmin):
    # columnas visibles en la lista de calificaciones
    list_display = (
        "calificacion_id",
        "ejercicio",
        "mercado",
        "instrumento",
        "secuencia_evento",
        "fecha_creacion",
    )

    # filtros laterales (sidebar del admin)
    list_filter = ("ejercicio", "mercado", "instrumento")

    # campos que admite el buscador del admin
    search_fields = ("instrumento__nombre",)
    # nota: el doble guion bajo "__" permite buscar por campo de relación ForeignKey

# ===============================================================
# Admin: Factor Valor (factores 8..37)
# ===============================================================
@admin.register(TblFactorValor)
class FactorValorAdmin(admin.ModelAdmin):
    # columnas que se mostrarán en la lista del admin
    list_display = ("id", "calificacion", "posicion", "valor")

    # permite filtrar por posición (ej. ver solo factores 8..19 o 20..37)
    list_filter = ("posicion",)
