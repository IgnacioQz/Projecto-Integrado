// static/js/session_timeout.js

class SessionManager {
    constructor(config) {
        this.sessionTimeout = config.sessionTimeout * 1000; // Convertir a ms
        this.warningTime = config.warningTime || 60000; // 1 minuto por defecto
        this.checkInterval = config.checkInterval || 10000; // 10 segundos
        this.checkUrl = config.checkUrl;
        this.loginUrl = config.loginUrl;
        
        this.lastActivity = Date.now();
        this.warningShown = false;
        this.sessionCheckInterval = null;
        this.countdownInterval = null;
        
        console.log('SessionManager iniciado:', {
            timeout: this.sessionTimeout / 1000 + 's',
            warningTime: this.warningTime / 1000 + 's',
            checkInterval: this.checkInterval / 1000 + 's'
        });
        
        this.init();
    }

    createStyledElement(tag, styles, content = '') {
    const element = document.createElement(tag);
    Object.assign(element.style, styles);
    if (content) element.innerHTML = content;
    return element;
}
    
    init() {
        // Detectar actividad del usuario
        ['mousedown', 'keydown', 'scroll', 'touchstart', 'mousemove'].forEach(event => {
            document.addEventListener(event, () => {
                this.resetActivity();
            }, true);
        });
        
        // Iniciar verificación periódica
        this.sessionCheckInterval = setInterval(() => this.checkSession(), this.checkInterval);
        
        // Verificar inmediatamente
        this.checkSession();
    }
    
    resetActivity() {
        const now = Date.now();
        const timeSinceLastActivity = now - this.lastActivity;
        
        // Solo resetear si pasó más de 1 segundo (evitar spam)
        if (timeSinceLastActivity > 1000) {
            console.log('Actividad detectada - reseteando timer');
            this.lastActivity = now;
            this.warningShown = false;
            this.hideWarning();
        }
    }
    
    checkSession() {
        const now = Date.now();
        const inactiveTime = now - this.lastActivity;
        const timeRemaining = this.sessionTimeout - inactiveTime;
        
        console.log('Check session:', {
            inactiveTime: Math.floor(inactiveTime / 1000) + 's',
            timeRemaining: Math.floor(timeRemaining / 1000) + 's'
        });
        
        // Mostrar advertencia si es necesario
        if (timeRemaining <= this.warningTime && timeRemaining > 0 && !this.warningShown) {
            console.log('Mostrando advertencia');
            this.showWarning(Math.floor(timeRemaining / 1000));
            this.warningShown = true;
        }
        
        // Si el tiempo expiró localmente, verificar con el servidor
        if (timeRemaining <= 0) {
            console.log('Tiempo expirado localmente - verificando con servidor');
            this.verifyWithServer();
        }
    }
    
    verifyWithServer() {
        console.log('Verificando sesión con servidor...');
    
        fetch(this.checkUrl, {
            method: 'GET',
            credentials: 'same-origin',
            headers: {
                'X-Requested-With': 'XMLHttpRequest'
            }
        })
        .then(response => {
            console.log('Respuesta del servidor:', response.status);
        
            // Intentar leer el JSON
            return response.json().then(data => ({
                status: response.status,
                data: data
            }));
        })
        .then(result => {
            console.log('Datos del servidor:', result);

            // Si la sesión expiró (401) o no está autenticado
            if (result.status === 401 || !result.data.authenticated) {
                console.log('Sesión expirada confirmada por servidor');
                this.handleSessionExpired();
            } else if (result.status === 200 && result.data.authenticated) {
                console.log('Sesión aún válida en servidor');
                // Aquí podrías decidir si extender el tiempo local o no
                // Por ahora, si expiró localmente, cerramos igual
                this.handleSessionExpired();
            }
        })
        .catch(error => {
            console.error('Error verificando sesión:', error);
            // En caso de error de red, también cerrar sesión
            this.handleSessionExpired();
        });
    }
    
    showWarning(secondsRemaining) {
    if (document.getElementById('session-warning')) {
        return;
    }
    
    console.log('Mostrando modal de advertencia');
    
    // Crear overlay
    const overlay = document.createElement('div');
    overlay.id = 'session-warning';
    Object.assign(overlay.style, {
        position: 'fixed',
        inset: '0',
        width: '100vw',
        height: '100vh',
        margin: '0',
        padding: '0',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'rgba(0, 0, 0, 0.75)',
        zIndex: '999999999',
        backdropFilter: 'blur(5px)'
    });
    
    // Crear contenedor
    const content = document.createElement('div');
    Object.assign(content.style, {
        background: 'white',
        padding: '45px 35px',
        borderRadius: '16px',
        textAlign: 'center',
        maxWidth: '480px',
        width: '90%',
        boxShadow: '0 20px 60px rgba(0, 0, 0, 0.5)',
        margin: '0',
        position: 'relative'
    });
    
    // Crear título
    const title = document.createElement('h2');
    title.textContent = '⚠️ Sesión por expirar';
    Object.assign(title.style, {
        color: '#e74c3c',
        margin: '0 0 25px 0',
        padding: '0',
        fontSize: '30px',
        fontWeight: '700',
        fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif'
    });
    
    // Crear texto
    const text = document.createElement('p');
    Object.assign(text.style, {
        color: '#34495e',
        fontSize: '18px',
        margin: '0 0 35px 0',
        padding: '0',
        lineHeight: '1.7',
        fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif'
    });
    
    // Crear countdown
    const countdown = document.createElement('strong');
    countdown.id = 'countdown';
    countdown.textContent = secondsRemaining;
    Object.assign(countdown.style, {
        color: '#e74c3c',
        fontSize: '42px',
        fontWeight: '800',
        display: 'inline-block',
        minWidth: '60px',
        padding: '8px 16px',
        background: 'rgba(231, 76, 60, 0.1)',
        borderRadius: '8px',
        margin: '0 5px'
    });
    
    text.innerHTML = 'Tu sesión expirará en ';
    text.appendChild(countdown);
    text.innerHTML += ' segundos por inactividad.';
    
    // Crear botón
    const button = document.createElement('button');
    button.id = 'stay-logged';
    button.textContent = 'Mantenerme conectado';
    Object.assign(button.style, {
        background: 'linear-gradient(135deg, #3498db 0%, #2c3e50 100%)',
        color: 'white',
        border: 'none',
        padding: '16px 40px',
        borderRadius: '10px',
        cursor: 'pointer',
        fontSize: '18px',
        fontWeight: '600',
        boxShadow: '0 8px 20px rgba(52, 152, 219, 0.3)',
        fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
        textTransform: 'uppercase',
        letterSpacing: '1px',
        transition: 'all 0.3s ease'
    });
    
    // Ensamblar
    content.appendChild(title);
    content.appendChild(text);
    content.appendChild(button);
    overlay.appendChild(content);
    document.body.appendChild(overlay);
    
    // Countdown interval
    this.countdownInterval = setInterval(() => {
        secondsRemaining--;
        const countdownEl = document.getElementById('countdown');
        if (countdownEl) {
            countdownEl.textContent = secondsRemaining;
        }
        if (secondsRemaining <= 0) {
            clearInterval(this.countdownInterval);
            this.handleSessionExpired();
        }
    }, 1000);
    
    // Event listeners del botón
    button.addEventListener('mouseenter', function() {
        this.style.background = 'linear-gradient(135deg, #2980b9 0%, #1a252f 100%)';
        this.style.transform = 'translateY(-3px)';
        this.style.boxShadow = '0 12px 28px rgba(52, 152, 219, 0.4)';
    });
    
    button.addEventListener('mouseleave', function() {
        this.style.background = 'linear-gradient(135deg, #3498db 0%, #2c3e50 100%)';
        this.style.transform = 'translateY(0)';
        this.style.boxShadow = '0 8px 20px rgba(52, 152, 219, 0.3)';
    });
    
    button.addEventListener('click', () => {
        this.resetActivity();
        fetch(window.location.href, { 
            method: 'GET',
            credentials: 'same-origin' 
        }).then(() => {
            console.log('Sesión renovada en servidor');
        });
    });
}
    
    hideWarning() {
        const warning = document.getElementById('session-warning');
        if (warning) {
            console.log('Ocultando modal de advertencia');
            warning.remove();
        }
        if (this.countdownInterval) {
            clearInterval(this.countdownInterval);
            this.countdownInterval = null;
        }
    }
    
    handleSessionExpired() {
        console.log('Manejando sesión expirada - redirigiendo a login');
        
        // Detener todos los intervalos
        if (this.sessionCheckInterval) {
            clearInterval(this.sessionCheckInterval);
            this.sessionCheckInterval = null;
        }
        if (this.countdownInterval) {
            clearInterval(this.countdownInterval);
            this.countdownInterval = null;
        }
        
        this.hideWarning();
        
        // Mostrar alerta
        alert('Tu sesión ha expirado por inactividad.');
        
        // Redirigir inmediatamente
        window.location.href = `${this.loginUrl}?next=${encodeURIComponent(window.location.pathname)}`;
    }
    
    destroy() {
        console.log('Destruyendo SessionManager');
        if (this.sessionCheckInterval) {
            clearInterval(this.sessionCheckInterval);
        }
        if (this.countdownInterval) {
            clearInterval(this.countdownInterval);
        }
        this.hideWarning();
    }
}

// Exportar para uso global
window.SessionManager = SessionManager;