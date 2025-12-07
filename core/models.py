# =============================================================================
# models.py — Modelos del Mantenedor de Calificaciones
# =============================================================================
# Contiene:
# 1) Catálogos base (Mercado, Instrumento, TipoIngreso, FactorDef)
# 2) Evidencia de carga (ArchivoFuente)
# 3) Modelos de negocio (Calificacion, FactorValor)
# -----------------------------------------------------------------------------

# =============================================================================
# IMPORTS
# =============================================================================
from django.db import models
from django.core.validators import MinValueValidator
from django.core.exceptions import ValidationError
from django.contrib.auth.models import User


# =============================================================================
# CATÁLOGOS BASE
# =============================================================================
class TblMercado(models.Model):
    """Catálogo de mercados (ej.: ACCIONES, CFI, FONDOS MUTUOS, etc.)."""

    mercado_id = models.AutoField(primary_key=True)
    nombre = models.CharField(max_length=60, unique=True, verbose_name="Nombre del Mercado")
    codigo = models.CharField(max_length=10, blank=True, verbose_name="Código (opcional)")
    activo = models.BooleanField(default=True)

    class Meta:
        db_table = "TBL_MERCADO"
        verbose_name = "Mercado"
        verbose_name_plural = "Mercados"
        ordering = ["nombre"]

    def __str__(self) -> str:
        return self.nombre


class TblInstrumento(models.Model):
    """Catálogo maestro de instrumentos financieros."""

    instrumento_id = models.AutoField(primary_key=True)
    nombre = models.CharField(max_length=100, verbose_name="Nombre del Instrumento")
    tipo_instrumento = models.CharField(max_length=20, verbose_name="Tipo de Instrumento")

    class Meta:
        db_table = "TBL_INSTRUMENTO"
        verbose_name = "Instrumento"
        verbose_name_plural = "Instrumentos"

    def __str__(self) -> str:
        return f"{self.nombre} ({self.tipo_instrumento})"


class TblTipoIngreso(models.Model):
    """Catálogo de tipos/fuentes de ingreso para calificaciones."""

    tipo_ingreso_id = models.AutoField(primary_key=True)
    nombre_tipo_ingreso = models.CharField(max_length=50, verbose_name="Nombre del Tipo de Ingreso")
    prioridad = models.IntegerField(
        verbose_name="Prioridad",
        help_text="Regla de prevalencia (p.ej. Corredor > Bolsa)",
    )

    class Meta:
        db_table = "TBL_TIPO_INGRESO"
        verbose_name = "Tipo de Ingreso"
        verbose_name_plural = "Tipos de Ingreso"
        ordering = ["prioridad"]

    def __str__(self) -> str:
        return f"{self.nombre_tipo_ingreso} (Prioridad {self.prioridad})"


class TblFactorDef(models.Model):
    """Definición de factores tributarios (posiciones 8-37)."""

    posicion = models.PositiveSmallIntegerField(unique=True)
    codigo = models.CharField(max_length=30, blank=True)
    nombre = models.CharField(max_length=255)
    descripcion = models.TextField(blank=True)
    activo = models.BooleanField(default=True)

    class Meta:
        db_table = "TBL_FACTOR_DEF"
        ordering = ["posicion"]

    def __str__(self) -> str:
        return f"{self.posicion} - {self.nombre}"


# =============================================================================
# MODELOS DE CARGA Y EVIDENCIA
# =============================================================================
class TblArchivoFuente(models.Model):
    """Registro de archivos subidos para carga masiva (trazabilidad/evidencia)."""

    archivo_fuente_id = models.AutoField(primary_key=True)

    # Nombre legible del archivo que subió el usuario
    nombre_archivo = models.CharField(
        max_length=255,
        verbose_name="Nombre del Archivo",
    )

    # Archivo físico: Django lo guarda usando DEFAULT_FILE_STORAGE (S3)
    archivo = models.FileField(
        upload_to="calificaciones/%Y/%m/%d",
        null=True,
        blank=True,
        verbose_name="Archivo subido (S3 / almacenamiento de archivos)",
    )

    # Campo antiguo que ya tenías. Lo dejamos opcional para no romper nada.
    ruta_almacenamiento = models.CharField(
        max_length=255,
        blank=True,
        verbose_name="Ruta de Almacenamiento (legacy)",
        help_text="Opcional; se puede dejar vacío cuando se usa S3.",
    )

    fecha_subida = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Fecha de Subida",
    )

    usuario = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="archivos_subidos",
        verbose_name="Usuario que subió el archivo",
    )

    class Meta:
        db_table = "TBL_ARCHIVO_FUENTE"
        verbose_name = "Archivo Fuente"
        verbose_name_plural = "Archivos Fuente"
        ordering = ["-fecha_subida"]

    def __str__(self) -> str:
        return self.nombre_archivo


# =============================================================================
# MODELOS PRINCIPALES DE NEGOCIO
# =============================================================================
class TblCalificacion(models.Model):
    """Entidad principal: Calificación tributaria (cabecera)."""

    calificacion_id = models.AutoField(primary_key=True)

    # ----------------------------
    # Contexto / Identificación
    # ----------------------------
    mercado = models.ForeignKey(
        "core.TblMercado",
        on_delete=models.PROTECT,
        db_column="mercado_id",
        verbose_name="Mercado",
    )
    instrumento_text = models.CharField(max_length=120, verbose_name="Instrumento")
    instrumento = models.ForeignKey(
        "core.TblInstrumento",
        on_delete=models.PROTECT,
        db_column="instrumento_id",
        null=True,
        blank=True,
        verbose_name="Instrumento (catálogo, opcional)",
    )
    tipo_ingreso = models.ForeignKey(
        "core.TblTipoIngreso",
        on_delete=models.PROTECT,
        db_column="tipo_ingreso_id",
        verbose_name="Tipo de Ingreso",
    )
    descripcion = models.CharField(max_length=255, blank=True, verbose_name="Descripción")

    # ----------------------------
    # Fechas y control
    # ----------------------------
    fecha_pago_dividendo = models.DateField(verbose_name="Fecha Pago")
    ejercicio = models.IntegerField(verbose_name="Año")
    secuencia_evento = models.IntegerField(
        validators=[MinValueValidator(10001)],
        help_text="Debe ser mayor a 10000",
        verbose_name="Secuencia Evento",
    )
    fecha_creacion = models.DateField(auto_now_add=True)
    fecha_modificacion = models.DateTimeField(auto_now=True)

    # ----------------------------
    # Valores de la calificación
    # ----------------------------
    dividendo = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    valor_historico = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    factor_actualizacion = models.DecimalField(max_digits=10, decimal_places=6, default=0)
    isfut = models.BooleanField(default=False, verbose_name="ISFUT")

    # ----------------------------
    # Trazabilidad / Evidencia
    # ----------------------------
    usuario = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        db_column="usuario_modificacion_id",
        verbose_name="Usuario Modificación",
    )
    archivo_fuente = models.ForeignKey(
        "core.TblArchivoFuente",
        on_delete=models.SET_NULL,
        db_column="archivo_fuente_id",
        null=True,
        blank=True,
        related_name="calificaciones",
        verbose_name="Archivo Fuente",
    )

    class Meta:
        db_table = "TBL_CALIFICACION"
        verbose_name = "Calificación Tributaria"
        verbose_name_plural = "Calificaciones Tributarias"
        ordering = ["-fecha_creacion"]
        indexes = [
            models.Index(fields=["ejercicio", "mercado"]),
            models.Index(fields=["secuencia_evento"]),
        ]

    def clean(self):
        """Validaciones de negocio adicionales a nivel de modelo."""
        if self.secuencia_evento and self.secuencia_evento <= 10000:
            raise ValidationError({"secuencia_evento": "La secuencia debe ser > 10000"})

    def __str__(self) -> str:
        return f"Cal #{self.calificacion_id} {self.mercado} {self.instrumento_text} ({self.ejercicio})"


class TblFactorValor(models.Model):
    """Detalle de factores por calificación (posiciones 8-37)."""

    id = models.AutoField(primary_key=True)
    calificacion = models.ForeignKey(
        TblCalificacion,
        on_delete=models.CASCADE,
        related_name="factores",
        verbose_name="Calificación",
    )
    posicion = models.PositiveSmallIntegerField(verbose_name="Posición (8..37)")
    monto_base = models.DecimalField(
        max_digits=16, decimal_places=2, null=True, blank=True, verbose_name="Monto Base"
    )
    valor = models.DecimalField(
        max_digits=12, decimal_places=8, verbose_name="Factor Calculado (0..1)"
    )
    factor_def = models.ForeignKey(
        "core.TblFactorDef",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        db_column="factor_def_id",
        related_name="valores",
    )

    class Meta:
        db_table = "TBL_FACTOR_VALOR"
        unique_together = [("calificacion", "posicion")]
        indexes = [models.Index(fields=["calificacion", "posicion"])]

    def clean(self):
        """Validaciones del detalle (rango de posición y valor)."""
        if not (8 <= self.posicion <= 37):
            raise ValidationError({"posicion": "La posición debe estar entre 8 y 37"})
        if self.valor is not None and not (0 <= self.valor <= 1):
            raise ValidationError({"valor": "El factor debe estar entre 0 y 1"})

    def __str__(self) -> str:
        # Nota: Django crea el atributo FK_id (<fk>_id). Aquí es válido usar calificacion_id.
        return f"C{self.calificacion_id}-F{self.posicion}={self.valor}"
