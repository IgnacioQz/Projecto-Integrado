from django.urls import path
from . import views
from .views_audit import auditoria_list, audit_ping 
from . import views_carga as carga_views

urlpatterns = [
    # ==========================================================================
    # Público / Autenticación
    # ==========================================================================
    path("", views.welcome_view, name="welcome"),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),

    # ==========================================================================
    # Home según rol
    # - Admin -> dashboard
    # - Corredor / Analista -> main (listado)
    # ==========================================================================
    path("dashboard/", views.dashboard, name="dashboard"),
    path("main/", views.main_view, name="main"),

    # ==========================================================================
    # Calificaciones
    # ==========================================================================
    # Paso 1: creación (form inicial)
    path("calificaciones/nueva/", views.carga_manual_view, name="carga_manual"),

    # Paso 2: edición de montos/factores
    path("calificaciones/<int:pk>/editar/", views.calificacion_edit, name="calificacion_edit"),

    # Eliminación múltiple
    path("calificaciones/eliminar-multiples/", views.calificacion_delete, name="calificacion_delete_multiple"),

    # ==========================================================================
    # Carga masiva 
    # ==========================================================================
    path("calificaciones/carga-masiva/", carga_views.carga_archivo, name="carga_archivo"),
    path("calificaciones/carga-masiva/confirmar/", carga_views.carga_confirmar, name="carga_archivo_confirmar"),
    # ==========================================================================
    # Auditoría (placeholder)
    # ==========================================================================
    path("auditoria/", auditoria_list, name="auditoria_list"),  
    path("audit-ping/", audit_ping, name="audit_ping"),


    # ==========================================================================
    # vista detalles calificacion
    # ==========================================================================
    path("calificaciones/<int:pk>/detalles/", views.calificacion_detalles, name="calificacion_detalles"),
    # ==========================================================================
 
]



