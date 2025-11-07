from django.core.management.base import BaseCommand
from django.contrib.auth.models import User, Group, Permission
from django.contrib.contenttypes.models import ContentType
from core.models import TblCalificacion

class Command(BaseCommand):
    help = "Crea grupos (roles), asigna permisos y usuarios base"

    def handle(self, *args, **kwargs):
        admin_g, _ = Group.objects.get_or_create(name="Administrador")
        corredor_g, _ = Group.objects.get_or_create(name="Corredor")
        analista_g, _ = Group.objects.get_or_create(name="AnalistaTributario")

        ct_calif = ContentType.objects.get_for_model(TblCalificacion)
        p_add_c = Permission.objects.get(codename="add_tblcalificacion", content_type=ct_calif)
        p_chg_c = Permission.objects.get(codename="change_tblcalificacion", content_type=ct_calif)
        p_del_c = Permission.objects.get(codename="delete_tblcalificacion", content_type=ct_calif)
        p_view_c= Permission.objects.get(codename="view_tblcalificacion", content_type=ct_calif)

        ct_user = ContentType.objects.get_for_model(User)
        p_add_u = Permission.objects.get(codename="add_user", content_type=ct_user)
        p_chg_u = Permission.objects.get(codename="change_user", content_type=ct_user)
        p_del_u = Permission.objects.get(codename="delete_user", content_type=ct_user)
        p_view_u= Permission.objects.get(codename="view_user", content_type=ct_user)

        admin_g.permissions.set([p_add_u,p_chg_u,p_del_u,p_view_u,p_add_c,p_chg_c,p_del_c,p_view_c])
        corredor_g.permissions.set([p_add_c,p_chg_c,p_del_c,p_view_c])
        analista_g.permissions.set([p_view_c])

        # usuarios
        su, created = User.objects.get_or_create(username="admin", defaults={
            "email":"admin@nuam.cl"
        })
        if created:
            su.set_password("Admin123!")
            su.is_superuser = True
            su.is_staff = True
            su.save()
            self.stdout.write(self.style.SUCCESS("Superusuario 'admin' creado"))
        else:
            self.stdout.write("Superusuario 'admin' ya existe")

        c, created = User.objects.get_or_create(username="corredor1", defaults={
            "email":"corredor1@nuam.cl"
        })
        if created:
            c.set_password("Corredor123!")
            c.save()
        c.groups.add(corredor_g)

        a, created = User.objects.get_or_create(username="analista1", defaults={
            "email":"analista1@nuam.cl"
        })
        if created:
            a.set_password("Analista123!")
            a.save()
        a.groups.add(analista_g)

        self.stdout.write(self.style.SUCCESS("Roles, permisos y usuarios listos."))
