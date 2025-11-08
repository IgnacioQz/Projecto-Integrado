from django.urls import path
from . import views

urlpatterns = [
    # =============================================================================
    # Páginas base / Autenticación
    # =============================================================================
    path('', views.welcome_view, name='welcome'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('main/', views.main_view, name='main'),

    path('dashboard/', views.dashboard, name='dashboard'),


    # =============================================================================
    # CRUD de Calificaciones Tributarias
    # =============================================================================
    # PASO 1: Crear calificación (datos básicos)
    path('calificaciones/nueva/', views.carga_manual_view, name='carga_manual'),
    
    # PASO 2: Editar montos y calcular factores
    path('calificaciones/<int:pk>/editar/', views.calificacion_edit, name='calificacion_edit'),
    
    # Eliminar calificaciones
    path('calificaciones/<int:pk>/eliminar/', views.calificacion_delete, name='calificacion_delete'),
    path('calificaciones/eliminar-multiples/', views.calificacion_delete_multiple, name='calificacion_delete_multiple'),

    # =============================================================================
    # Carga Masiva 
    # =============================================================================
    path('carga-masiva/', views.carga_masiva_view, name='carga_masiva'),
]