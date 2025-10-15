from django.urls import path
from . import views

urlpatterns = [
    path('', views.welcome_view, name='welcome'),
    path('login/', views.login_view, name='login'),
    path('main/', views.main_view, name='main'),
    path('logout/', views.logout_view, name='logout'),
]