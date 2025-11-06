# core/models.py
from django.db import models
from django.core.validators import MinValueValidator
from django.core.exceptions import ValidationError
from django.contrib.auth.models import User

# =============================================================================
# Catálogos Base
# =============================================================================

class TblInstrumento(models.Model):
    """
    Catálogo maestro de instrumentos financieros.
    
    Attributes:
        instrumento_id (AutoField): ID único del instrumento
        nombre (str): Nombre/descripción del instrumento
        tipo_instrumento (str): Clasificación (ej: ACCIÓN, BONO)
    
    Note:
        Opcional para ingreso manual donde el usuario puede escribir libremente
        en el campo instrumento_text de TblCalificacion
    """
    instrumento_id = models.AutoField(primary_key=True)
    nombre = models.CharField(
        max_length=100, 
        verbose_name="Nombre del Instrumento"
    )
    tipo_instrumento = models.CharField(
        max_length=20, 
        verbose_name="Tipo de Instrumento"
    )

    class Meta:
        verbose_name = "Instrumento"
        verbose_name_plural = "Instrumentos"
        db_table = "TBL_INSTRUMENTO"

    def __str__(self):
        return f"{self.nombre} ({self.tipo_instrumento})"


class TblTipoIngreso(models.Model):
    """
    Catálogo de tipos/fuentes de ingreso para calificaciones.
    
    Attributes:
        tipo_ingreso_id (AutoField): ID único del tipo
        nombre_tipo_ingreso (str): Nombre descriptivo (ej: Corredor, Bolsa)
        prioridad (int): Nivel para resolver conflictos entre fuentes
        
    Note:
        La prioridad permite establecer precedencia cuando existen
        múltiples fuentes para una misma calificación
    """
    tipo_ingreso_id = models.AutoField(primary_key=True)
    nombre_tipo_ingreso = models.CharField(
        max_length=50, 
        verbose_name="Nombre del Tipo de Ingreso"
    )
    prioridad = models.IntegerField(
        verbose_name="Prioridad",
        help_text="Regla de prevalencia (p.ej. Corredor > Bolsa)"
    )

    class Meta:
        verbose_name = "Tipo de Ingreso"
        verbose_name_plural = "Tipos de Ingreso"
        db_table = "TBL_TIPO_INGRESO"
        ordering = ["prioridad"]

    def __str__(self):
        return f"{self.nombre_tipo_ingreso} (Prioridad {self.prioridad})"


class TblFactorDef(models.Model):
    """
    Definición de factores tributarios (posiciones 8-37).
    
    Attributes:
        posicion (int): Número de posición (8-37)
        codigo (str): Código corto opcional (ej: F8)
        nombre (str): Descripción del factor
        descripcion (str): Detalle explicativo
        activo (bool): Indica si el factor está vigente
    """
    posicion = models.PositiveSmallIntegerField(unique=True)
    codigo = models.CharField(max_length=30, blank=True)
    nombre = models.CharField(max_length=255)
    descripcion = models.TextField(blank=True)
    activo = models.BooleanField(default=True)

    class Meta:
        db_table = "TBL_FACTOR_DEF"
        ordering = ["posicion"]

    def __str__(self):
        return f"{self.posicion} - {self.nombre}"


# =============================================================================
# Modelos de Carga y Evidencia
# =============================================================================

class TblArchivoFuente(models.Model):
    """
    Registro de archivos subidos para carga masiva.
    
    Attributes:
        archivo_fuente_id (AutoField): ID único del archivo
        nombre_archivo (str): Nombre original del archivo
        ruta_almacenamiento (str): Path donde se guardó
        fecha_subida (datetime): Timestamp de la carga
        usuario (User): Usuario que realizó la carga
    """
    archivo_fuente_id = models.AutoField(primary_key=True)
    nombre_archivo = models.CharField(
        max_length=255, 
        verbose_name="Nombre del Archivo"
    )
    ruta_almacenamiento = models.CharField(
        max_length=255, 
        verbose_name="Ruta de Almacenamiento"
    )
    fecha_subida = models.DateTimeField(
        auto_now_add=True, 
        verbose_name="Fecha de Subida"
    )
    usuario = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="archivos_subidos",
        verbose_name="Usuario que subió el archivo",
    )

    class Meta:
        verbose_name = "Archivo Fuente"
        verbose_name_plural = "Archivos Fuente"
        db_table = "TBL_ARCHIVO_FUENTE"
        ordering = ["-fecha_subida"]

    def __str__(self):
        return self.nombre_archivo


# =============================================================================
# Modelos Principales de Negocio
# =============================================================================

class TblCalificacion(models.Model):
    """
    Entidad principal: Calificación tributaria.
    
    Se puede crear mediante:
    1. Ingreso manual (proceso en 2 pasos)
    2. Carga masiva desde archivo
    
    Attributes:
        Identificación:
            calificacion_id (AutoField): ID único
            mercado (str): Mercado aplicable
            instrumento_text (str): Nombre ingresado manualmente
            instrumento (FK): Referencia opcional al catálogo
            tipo_ingreso (FK): Origen/fuente de la calificación
            
        Datos principales:
            fecha_pago_dividendo (date): Fecha efectiva
            ejercicio (int): Año fiscal
            secuencia_evento (int): Número > 10000
            
        Valores:
            dividendo (Decimal): Monto del dividendo
            valor_historico (Decimal): Valor base
            factor_actualizacion (Decimal): Multiplicador monetario
            isfut (bool): Marcador ISFUT
            
        Trazabilidad:
            usuario (FK): Último usuario que modificó
            archivo_fuente (FK): Archivo origen si fue carga masiva
            fecha_creacion (date): Fecha inicial
            fecha_modificacion (datetime): Última actualización
    """
    calificacion_id = models.AutoField(primary_key=True)

    # ----------------------------
    # Contexto / Identificación
    # ----------------------------
    mercado = models.CharField(max_length=60, verbose_name="Mercado")

    # Instrumento libre (lo escribe el corredor)
    instrumento_text = models.CharField(max_length=120, verbose_name="Instrumento")

    # Instrumento normalizado (opcional)
    instrumento = models.ForeignKey(
        "core.TblInstrumento",
        on_delete=models.PROTECT,
        db_column="instrumento_id",
        null=True,
        blank=True,
        verbose_name="Instrumento (catálogo, opcional)",
    )

    # Origen de la calificación
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

    # Secuencia > 10000 (regla de negocio que has pedido)
    secuencia_evento = models.IntegerField(
        validators=[MinValueValidator(10001)],
        help_text="Debe ser mayor a 10000",
        verbose_name="Secuencia Evento",
    )

    # Timestamps de creación / modificación
    # (DateField para creación y DateTimeField para última modificación)
    fecha_creacion = models.DateField(auto_now_add=True)
    fecha_modificacion = models.DateTimeField(auto_now=True)

    # ----------------------------
    # Valores de la calificación
    # ----------------------------
    dividendo = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    valor_historico = models.DecimalField(max_digits=15, decimal_places=2, default=0)

    # Marcador de ISFUT (según normativa)
    isfut = models.BooleanField(default=False, verbose_name="ISFUT")

    # Multiplicador monetario opcional (IPC/UF, etc.). No es un factor 8..37.
    # Si no se usa indexación, puede quedar en 0 o 1 (según tu preferencia).
    factor_actualizacion = models.DecimalField(max_digits=10, decimal_places=6, default=0)

    # ----------------------------
    # Trazabilidad / Evidencia
    # ----------------------------
    usuario = models.ForeignKey(
        User,
        on_delete=models.PROTECT,          # no borrar usuario si hay calificaciones
        db_column="usuario_modificacion_id",
        verbose_name="Usuario Modificación",
    )

    # Archivo de donde provino (solo en carga masiva). 
    archivo_fuente = models.ForeignKey(
        "core.TblArchivoFuente",
        on_delete=models.SET_NULL,         # si borran el archivo, no perder la calificación
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
        # Índices útiles para búsquedas y filtros
        indexes = [
            models.Index(fields=["ejercicio", "mercado"]),
            models.Index(fields=["secuencia_evento"]),
        ]

    def clean(self):
        """
        Validaciones de negocio adicionales a nivel de modelo.
        """
        if self.secuencia_evento and self.secuencia_evento <= 10000:
            raise ValidationError({"secuencia_evento": "La secuencia debe ser > 10000"})

    def __str__(self):
        # Ejemplo: "Cal #5 ACC INSTRUMENTO XYZ (2025)"
        return f"Cal #{self.calificacion_id} {self.mercado} {self.instrumento_text} ({self.ejercicio})"


class TblFactorValor(models.Model):
    """
    Detalle de factores por calificación.
    
    Attributes:
        calificacion (FK): Calificación padre
        posicion (int): Número de factor (8-37)
        monto_base (Decimal): Valor ingresado por usuario
        valor (Decimal): Factor calculado (0-1, 8 decimales)
        factor_def (FK): Referencia a la definición del factor
        
    Rules:
        - Posición debe estar entre 8 y 37
        - Valor debe estar entre 0 y 1
        - No puede haber factores duplicados para una calificación
    """
    id = models.AutoField(primary_key=True)

    # FK al maestro (si se borra la calificación, se borra el detalle)
    calificacion = models.ForeignKey(
        TblCalificacion,
        on_delete=models.CASCADE,
        related_name="factores",
        verbose_name="Calificación",
    )

    # Número de factor (8..37). Se valida en clean().
    posicion = models.PositiveSmallIntegerField(verbose_name="Posición (8..37)")

    # Monto ingresado por el usuario para esa posición (puede ser 0 o null).
    monto_base = models.DecimalField(
        max_digits=16, decimal_places=2, null=True, blank=True, verbose_name="Monto Base"
    )

    # Factor calculado (0..1), 8 decimales.
    valor = models.DecimalField(
        max_digits=12, decimal_places=8, verbose_name="Factor Calculado (0..1)"
    )
    
    factor_def = models.ForeignKey(
    "core.TblFactorDef",
    on_delete=models.PROTECT,
    null=True, blank=True,
    db_column="factor_def_id",
    related_name="valores",
    )

    class Meta:
        db_table = "TBL_FACTOR_VALOR"
        # Evita duplicados de posición para la misma calificación
        unique_together = [("calificacion", "posicion")]
        # Índice para filtrar rápido por calificación y ordenar por posición
        indexes = [models.Index(fields=["calificacion", "posicion"])]

    def clean(self):
        """
        Validaciones del detalle:
        - posición válida
        - factor dentro del rango [0, 1]
        """
        if not (8 <= self.posicion <= 37):
            raise ValidationError({"posicion": "La posición debe estar entre 8 y 37"})
        if self.valor is not None and not (0 <= self.valor <= 1):
            raise ValidationError({"valor": "El factor debe estar entre 0 y 1"})

    def __str__(self):
        # Nota: usamos pk para evitar acceder a FKs pesados en representaciones
        return f"C{self.calificacion_id}-F{self.posicion}={self.valor}"
        # (Django expone calificacion_id como atributo del FK; alternativamente: f"C{self.calificacion.pk}-F{self.posicion}={self.valor}")