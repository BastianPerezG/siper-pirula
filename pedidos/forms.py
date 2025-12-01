from django import forms
from django.forms import inlineformset_factory
from .validators import validar_rut
from .models import Pedido, PedidoItem, Cliente
from inventario.models import Producto
from django.contrib.auth.models import User

class PedidoForm(forms.ModelForm):
    class Meta:
        model = Pedido
        fields = ["cliente", "nombre", "correo", "telefono"]

    def __init__(self, *args, **kwargs):
        negocio = kwargs.pop("negocio", None)
        super().__init__(*args, **kwargs)

        if negocio:
            self.fields["cliente"].queryset = Cliente.objects.filter(
                negocio=negocio, activo=True
            )
        self.fields["cliente"].required = False


class PedidoItemForm(forms.ModelForm):
    class Meta:
        model = PedidoItem
        fields = ["producto", "cantidad", "precio"]

    def __init__(self, *args, **kwargs):
        negocio = kwargs.pop("negocio", None)
        super().__init__(*args, **kwargs)

        if negocio:
            self.fields["producto"].queryset = Producto.objects.filter(
                negocio=negocio, activo=True
            )


PedidoItemFormSet = inlineformset_factory(
    Pedido,
    PedidoItem,
    form=PedidoItemForm,
    extra=3,
    can_delete=True,
)

class RegistroClienteForm(forms.ModelForm):
    username = forms.CharField(
        label="Usuario",
        max_length=150,
        help_text="Nombre de usuario para iniciar sesión.",
    )
    password1 = forms.CharField(
        label="Contraseña",
        widget=forms.PasswordInput,
    )
    password2 = forms.CharField(
        label="Repite la contraseña",
        widget=forms.PasswordInput,
    )

    rut = forms.CharField(
        max_length=12,
        required=False,
        validators=[validar_rut],
        label="RUT (opcional)",
    )

    class Meta:
        model = Cliente
        fields = ["nombre", "rut", "correo", "telefono", "direccion"]

    def clean_username(self):
        username = self.cleaned_data["username"]
        if User.objects.filter(username=username).exists():
            raise forms.ValidationError("Este nombre de usuario ya existe.")
        return username

    def clean(self):
        cleaned = super().clean()
        p1 = cleaned.get("password1")
        p2 = cleaned.get("password2")
        if p1 and p2 and p1 != p2:
            raise forms.ValidationError("Las contraseñas no coinciden.")
        return cleaned