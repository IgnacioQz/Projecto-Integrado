# core/urls.py
from django.urls import path
from . import views

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
    path("carga-masiva/", views.carga_masiva_view, name="carga_masiva"),
]
