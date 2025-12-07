from django.conf import settings

def session_settings(request):
    """
    Expone configuraciones de sesión a todos los templates.
    """
    return {
        'settings': {
            'SESSION_COOKIE_AGE': settings.SESSION_COOKIE_AGE,
        }
    }