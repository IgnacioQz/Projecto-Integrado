from django.urls import path
from . import views

urlpatterns = [
    # Páginas base / auth
    path('', views.welcome_view, name='welcome'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('main/', views.main_view, name='main'),

    # Sandbox (menú de pruebas)
    path('sandbox/', views.sandbox_view, name='sandbox'),

    # CRUD de calificaciones (sandbox)
    path('calificaciones/', views.calificacion_list, name='calificacion_list'),
    path('calificaciones/nueva/', views.carga_manual_view, name='carga_manual'),
    path('calificacion/edit/<int:pk>/', views.calificacion_edit, name='calificacion_edit'),

    # Mockups 
    path('carga_masiva/', views.carga_masiva_view, name='carga_masiva'),
]
