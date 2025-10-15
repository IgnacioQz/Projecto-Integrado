from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required

def welcome_view(request):
    return render(request, 'welcome.html')

def login_view(request):
    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '').strip()
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            return redirect('main')
        messages.error(request, 'Usuario o contraseña incorrectos.')
    return render(request, 'login.html')

@login_required(login_url='login')
def main_view(request):
    return render(request, 'main.html')

def logout_view(request):
    logout(request)
    return redirect('welcome')