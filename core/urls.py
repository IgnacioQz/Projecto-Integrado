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


    # =============================================================================
    # CRUD de Calificaciones Tributarias - Flujo unificado
    # =============================================================================
    # Listado
    path('calificaciones/', views.calificacion_list, name='calificacion_list'),
    
    # PASO 1: Crear calificación (datos básicos)
    # Usa carga_manual_view que renderiza cargaManual.html (mockup funcional)
    path('calificaciones/nueva/', views.carga_manual_view, name='carga_manual'),
    
    # PASO 2: Editar montos y calcular factores (posiciones 8-37)
    path('calificaciones/<int:pk>/editar/', views.calificacion_edit, name='calificacion_edit'),
    
    # Eliminar calificaciones
    path('calificaciones/<int:pk>/eliminar/', views.calificacion_delete, name='calificacion_delete'),
    path('calificaciones/eliminar-multiples/', views.calificacion_delete_multiple, name='calificacion_delete_multiple'),

    # =============================================================================
    # Carga Masiva (futuro)
    # =============================================================================
    path('carga-masiva/', views.carga_masiva_view, name='carga_masiva'),
]