from django.db import models
from django.contrib.auth.hashers import make_password, check_password

class SimpleUser(models.Model):
    username = models.CharField(max_length=150, unique=True)
    email = models.EmailField(blank=True)
    password = models.CharField(max_length=128)  # almacena hash

    def set_password(self, raw_password):
        # solo asigna el hash; no hace save() aquí
        self.password = make_password(raw_password)

    def check_password(self, raw_password):
        return check_password(raw_password, self.password)

    def __str__(self):
        return self.username
