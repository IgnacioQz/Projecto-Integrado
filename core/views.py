from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required

def welcome_view(request):
    return render(request, 'welcome.html')

def login_view(request):
    """
    - GET: muestra el formulario de login.
    - POST: recibe username/password desde el form.
      1) authenticate(request, username, password) -> devuelve User o None.
         - authenticate comprueba las credenciales contra los backends (por defecto
           verifica contra auth.User y comprueba la contraseña hasheada).
      2) si user != None: login(request, user) -> crea la sesión del usuario.
      3) redirect a 'main' en caso de éxito; si falla muestra mensaje de error.
    """
    if request.method == 'POST':
        username = request.POST.get('username','').strip()
        password = request.POST.get('password','').strip()

        user = authenticate(request, username=username, password=password)
        if user is not None:
            # marca el usuario como autenticado en la sesión
            login(request, user)
            return redirect('main')
        # credenciales inválidas -> feedback al usuario
        messages.error(request, 'Usuario o contraseña incorrectos.')
    return render(request, 'login.html')

@login_required(login_url='login')
def main_view(request):
    # solo accesible si el usuario ha iniciado sesión
    return render(request, 'main.html')

def logout_view(request):
    # elimina la sesión del usuario
    logout(request)
    return redirect('welcome')

def carga_manual_view(request):
    return render(request, 'cargaManual.html')

def carga_masiva_view(request):
    return render(request, 'cargaMasiva.html')