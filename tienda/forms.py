from django import forms
from pedidos.validators import validar_rut

# Tienda FORMS

# tienda/forms.py

from django import forms
from pedidos.validators import validar_rut

class CheckoutForm(forms.Form):
    nombre = forms.CharField(
        label="Nombre",
        max_length=100,
        widget=forms.TextInput(attrs={
            "class": "w-full px-4 py-3 rounded-2xl border border-slate-200 "
                     "focus:outline-none focus:ring-2 focus:ring-slate-800",
            "placeholder": "Tu nombre",
        }),
    )

    rut = forms.CharField(
        label="RUT",
        max_length=12,
        required=False,
        validators=[validar_rut],
        help_text="Opcional, pero recomendado para identificar tu pedido.",
        widget=forms.TextInput(attrs={
            "class": "w-full px-4 py-3 rounded-2xl border border-slate-200 "
                     "focus:outline-none focus:ring-2 focus:ring-slate-800",
            "placeholder": "12.345.678-9",
        }),
    )

    correo = forms.EmailField(
        label="Correo electrónico",
        widget=forms.EmailInput(attrs={
            "class": "w-full px-4 py-3 rounded-2xl border border-slate-200 "
                     "focus:outline-none focus:ring-2 focus:ring-slate-800",
            "placeholder": "tucorreo@ejemplo.com",
        }),
    )

    telefono = forms.CharField(
        label="Teléfono",
        max_length=20,
        required=False,
        widget=forms.TextInput(attrs={
            "class": "w-full px-4 py-3 rounded-2xl border border-slate-200 "
                     "focus:outline-none focus:ring-2 focus:ring-slate-800",
            "placeholder": "+56 9 1234 5678",
        }),
    )

    # Usamos los mismos valores que envía el template: "RETIRO" / "WEBPAY"
    FORMA_PAGO_CHOICES = (
        ("RETIRO", "Pagar al retirar en la botillería"),
        ("WEBPAY", "Pagar ahora con Webpay"),
    )
    forma_pago = forms.ChoiceField(
        label="Forma de pago",
        choices=FORMA_PAGO_CHOICES,
        initial="RETIRO",
        widget=forms.RadioSelect,
    )

    crear_cuenta = forms.BooleanField(
        label="Crear cuenta con estos datos",
        required=False,
    )
