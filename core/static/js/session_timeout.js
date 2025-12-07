// static/js/session-timeout.js

class SessionManager {
    constructor(config) {
        this.sessionTimeout = config.sessionTimeout * 1000; // Convertir a ms
        this.warningTime = config.warningTime || 60000; // 1 minuto por defecto
        this.checkInterval = config.checkInterval || 30000; // 30 segundos
        this.checkUrl = config.checkUrl;
        this.loginUrl = config.loginUrl;
        
        this.lastActivity = Date.now();
        this.warningShown = false;
        this.sessionCheckInterval = null;
        this.countdownInterval = null;
        
        this.init();
    }
    
    init() {
        // Detectar actividad del usuario
        ['mousedown', 'keydown', 'scroll', 'touchstart'].forEach(event => {
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
        this.lastActivity = Date.now();
        this.warningShown = false;
        this.hideWarning();
    }
    
    checkSession() {
        const inactiveTime = Date.now() - this.lastActivity;
        const timeRemaining = this.sessionTimeout - inactiveTime;
        
        // Mostrar advertencia si es necesario
        if (timeRemaining <= this.warningTime && timeRemaining > 0 && !this.warningShown) {
            this.showWarning(Math.floor(timeRemaining / 1000));
            this.warningShown = true;
        }
        
        // Verificar si expiró
        if (timeRemaining <= 0) {
            this.verifyWithServer();
        }
    }
    
    verifyWithServer() {
        fetch(this.checkUrl, {
            method: 'GET',
            credentials: 'same-origin',
            headers: {
                'X-Requested-With': 'XMLHttpRequest'
            }
        })
        .then(response => {
            if (response.status === 403 || response.status === 401) {
                this.handleSessionExpired();
            }
        })
        .catch(error => {
            console.error('Error verificando sesión:', error);
        });
    }
    
    showWarning(secondsRemaining) {
        // Crear modal de advertencia
        const warning = document.createElement('div');
        warning.id = 'session-warning';
        warning.className = 'session-warning-overlay';
        
        warning.innerHTML = `
            <div class="session-warning-content">
                <h2 class="session-warning-title">⚠️ Sesión por expirar</h2>
                <p class="session-warning-text">
                    Tu sesión expirará en <strong id="countdown">${secondsRemaining}</strong> 
                    segundos por inactividad.
                </p>
                <button id="stay-logged" class="session-warning-button">
                    Mantenerme conectado
                </button>
            </div>
        `;
        
        document.body.appendChild(warning);
        
        // Actualizar countdown
        this.countdownInterval = setInterval(() => {
            secondsRemaining--;
            const countdownEl = document.getElementById('countdown');
            if (countdownEl) {
                countdownEl.textContent = secondsRemaining;
            }
            if (secondsRemaining <= 0) {
                clearInterval(this.countdownInterval);
            }
        }, 1000);
        
        // Botón para renovar sesión
        document.getElementById('stay-logged').addEventListener('click', () => {
            this.resetActivity();
            // Hacer petición para renovar la sesión
            fetch(window.location.href, { credentials: 'same-origin' });
        });
    }
    
    hideWarning() {
        const warning = document.getElementById('session-warning');
        if (warning) {
            warning.remove();
        }
        if (this.countdownInterval) {
            clearInterval(this.countdownInterval);
        }
    }
    
    handleSessionExpired() {
        clearInterval(this.sessionCheckInterval);
        this.hideWarning();
        alert('Tu sesión ha expirado por inactividad.');
        window.location.href = `${this.loginUrl}?next=${encodeURIComponent(window.location.pathname)}`;
    }
    
    destroy() {
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