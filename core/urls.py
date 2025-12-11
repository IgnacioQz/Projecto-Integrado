from django.urls import path
from . import views
from .views import audit as auditoria_views
from .views import carga as carga_views
from .views import mainv as main_views

urlpatterns = [
    # --- Público / Autenticación ---
    path("", main_views.welcome_view, name="welcome"),            # Página de bienvenida
    path("login/", main_views.login_view, name="login"),          # Iniciar sesión
    path("logout/", main_views.logout_view, name="logout"),       # Cerrar sesión

    # --- Inicio según rol ---
    path("dashboard/", main_views.dashboard, name="dashboard"),   # Panel de admin
    path("main/", main_views.main_view, name="main"),

    # --- Calificaciones ---
    path("calificaciones/nueva/",
         main_views.carga_manual_view, name="carga_manual"),

    path("calificaciones/<int:pk>/editar/",
         main_views.calificacion_edit, name="calificacion_edit"),

    path("calificaciones/eliminar-multiples/",
         main_views.calificacion_delete, name="calificacion_delete_multiple"),

    path("calificaciones/<int:pk>/detalles/",
         main_views.calificacion_detalles, name="calificacion_detalles"),

    # --- Carga masiva ---
    path("calificaciones/carga-masiva/",
         carga_views.carga_archivo, name="carga_archivo"),
    path("calificaciones/carga-masiva/confirmar/",
         carga_views.carga_confirmar, name="carga_archivo_confirmar"),

    # --- Auditoría ---
    path("auditoria/",
         auditoria_views.auditoria_list, name="auditoria_list"),
    path("audit-ping/",
         auditoria_views.audit_ping, name="audit_ping"),

    # --- Descarga de archivo fuente por calificación ---
    path(
        "archivos-fuente/<int:calificacion_id>/descargar/",
        auditoria_views.descargar_archivo_fuente,
        name="descargar_archivo_fuente",
    ),

    # --- Verificación de sesión ---
    path("check-session/", main_views.check_session, name="check_session"),
]
