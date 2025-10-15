from django.contrib import admin
from django import forms
from .models import SimpleUser

class SimpleUserCreationForm(forms.ModelForm):
    password1 = forms.CharField(label='Contraseña', widget=forms.PasswordInput)
    password2 = forms.CharField(label='Confirmar contraseña', widget=forms.PasswordInput)

    class Meta:
        model = SimpleUser
        fields = ('username', 'email')

    def clean_password2(self):
        p1 = self.cleaned_data.get('password1')
        p2 = self.cleaned_data.get('password2')
        if not p1 or p1 != p2:
            raise forms.ValidationError('Las contraseñas no coinciden.')
        return p2

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data['password1'])
        if commit:
            user.save()
        return user

class SimpleUserChangeForm(forms.ModelForm):
    # campo opcional para cambiar contraseña al editar
    password = forms.CharField(label='Contraseña (dejar en blanco para no cambiar)',
                               widget=forms.PasswordInput, required=False)

    class Meta:
        model = SimpleUser
        fields = ('username', 'email', 'password')

    def save(self, commit=True):
        user = super().save(commit=False)
        pw = self.cleaned_data.get('password')
        if pw:
            user.set_password(pw)
        if commit:
            user.save()
        return user

@admin.register(SimpleUser)
class SimpleUserAdmin(admin.ModelAdmin):
    form = SimpleUserChangeForm
    add_form = SimpleUserCreationForm
    list_display = ('username', 'email')

    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('username', 'email', 'password1', 'password2'),
        }),
    )
    fieldsets = (
        (None, {'fields': ('username', 'email', 'password')}),
    )

    def get_fieldsets(self, request, obj=None):
        # al crear devuelve add_fieldsets; al editar usa los fieldsets normales
        if obj is None:
            return self.add_fieldsets
        return super().get_fieldsets(request, obj)

