from django.shortcuts import render, redirect

def welcome_view(request):
    return render(request, 'welcome.html')

def login_view(request):
    # visual-only: no procesamiento POST, no autenticación
    return render(request, 'login.html')

def main_view(request):
    return render(request, 'main.html')

def logout_view(request):
    return redirect('welcome')