# core/migrations/0006_seed_factor_def.py
from django.db import migrations

def seed_factor_def(apps, schema_editor):
    TblFactorDef = apps.get_model("core", "TblFactorDef")
    data = [
        (8,  "Con crédito por IDPC generados a contar del 01.01.2017"),
        (9,  "Con crédito por IDPC acumulados hasta el 31.12.2016"),
        (10, "Con derecho a crédito por pago de IDPC voluntario"),
        (11, "Sin derecho a crédito"),
        (12, "Rentas provenientes del registro RAP y Diferencia Inicial de sociedad acogida al ex Art. 14 TER A) LIR"),
        (13, "Otras rentas percibidas sin prioridad en su orden de imputación"),
        (14, "Exceso de distribución desproporcionada (N°9 Art. 14 A)"),
        (15, "Utilidades afectadas con impuesto sustitutivo al FUT (ISFUT) Ley N°20.780"),
        (16, "Rentas generadas hasta el 31.12.1983 y/o utilidades afectadas con ISFUT de la Ley N°21.210"),
        (17, "Rentas Exentas de Impuesto Global Complementario (IGC) Art. 11, Ley 18.401, Afectas a Impuesto Adicional"),
        (18, "Rentas Exentas de IGC y/o Impuesto Adicional (IA)"),
        (19, "Ingresos No Constitutivos de Renta"),
        (20, "No sujetas a restitución hasta 31.12.2019 – Sin derecho a devolución"),
        (21, "No sujetas a restitución hasta 31.12.2019 – Con derecho a devolución"),
        (22, "No sujetas a restitución desde 01.01.2020 – Sin derecho a devolución"),
        (23, "No sujetas a restitución desde 01.01.2020 – Con derecho a devolución"),
        (24, "Sujetos a restitución – Sin derecho a devolución"),
        (25, "Sujetos a restitución – Con derecho a devolución"),
        (26, "Sujetos a restitución – Sin derecho a devolución"),
        (27, "Sujetos a restitución – Con derecho a devolución"),
        (28, "Crédito por IPE"),
        (29, "Factor 29 (ajusta el nombre real si aplica)"),
        (30, "Factor 30 (ajusta el nombre real si aplica)"),
        (31, "Factor 31 (ajusta el nombre real si aplica)"),
        (32, "Factor 32 (ajusta el nombre real si aplica)"),
        (33, "Factor 33 (ajusta el nombre real si aplica)"),
        (34, "Factor 34 (Imp. Tasas Adicionales, Art. 21 LIR"),
        (35, "3RA EFECTIVA DEL CRED. DEL FUT (TEF)"),
        (36, "3RA Tasa Efectiva del CRED. del FUT (TEF)"),
        (37, "Devolución de Capital, Art. 17 N°7 LIR"),
    ]
    for pos, nombre in data:
        TblFactorDef.objects.update_or_create(
            posicion=pos,
            defaults={
                "codigo": f"F{pos}",
                "nombre": nombre,
                "descripcion": "",
                "activo": True,
            },
        )

def link_existing_vals(apps, schema_editor):
    """Enlaza TblFactorValor existentes con el catálogo por posición."""
    TblFactorDef = apps.get_model("core", "TblFactorDef")
    TblFactorValor = apps.get_model("core", "TblFactorValor")
    defs = {d.posicion: d.id for d in TblFactorDef.objects.all()}
    for fv in TblFactorValor.objects.all():
        if fv.posicion in defs and getattr(fv, "factor_def_id", None) is None:
            fv.factor_def_id = defs[fv.posicion]
            fv.save(update_fields=["factor_def_id"])

class Migration(migrations.Migration):

    dependencies = [
        ("core", "0005_tblfactordef_tblfactorvalor_factor_def"),
    ]

    operations = [
        migrations.RunPython(seed_factor_def, migrations.RunPython.noop),
        migrations.RunPython(link_existing_vals, migrations.RunPython.noop),
    ]
