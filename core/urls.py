from django.urls import path
from . import views

# Definición de patrones URL para la aplicación core
# Organizado por funcionalidad/módulo para mejor mantenimiento
urlpatterns = [
    # =============================================================================
    # Autenticación y navegación base
    # =============================================================================
    path('', views.welcome_view, name='welcome'),          # Página inicial pública
    path('login/', views.login_view, name='login'),        # Login de usuarios
    path('logout/', views.logout_view, name='logout'),     # Cierre de sesión
    path('main/', views.main_view, name='main'),          # Dashboard principal (protegido)

    # =============================================================================
    # Gestión de Calificaciones - Carga Manual
    # =============================================================================
    path('calificaciones/nueva/', 
         views.carga_manual_view, 
         name='carga_manual'),                            # Paso 1: Crear calificación
    
    path('calificacion/edit/<int:pk>/', 
         views.calificacion_edit, 
         name='calificacion_edit'),                       # Paso 2: Editar/completar
    
    path('calificaciones/', 
         views.calificacion_list, 
         name='calificacion_list'),                       # Listar todas (temporal)

    # =============================================================================
    # Carga Masiva (pendiente implementar)
    # =============================================================================
    path('carga_masiva/', 
         views.carga_masiva_view, 
         name='carga_masiva'),                           # Vista placeholder
]
