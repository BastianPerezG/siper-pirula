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
        label="RUT",
    )

    class Meta:
        model = Cliente
        fields = ["nombre", "rut", "correo", "telefono"]

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
        
        # Validaciones de seguridad (Espejo de core/forms.py)
        if p1:
            # Largo mínimo
            if len(p1) < 6:
                raise forms.ValidationError("La contraseña debe tener al menos 6 caracteres.")

            # Mayúscula
            if not any(c.isupper() for c in p1):
                raise forms.ValidationError("La contraseña debe contener al menos una letra mayúscula.")

            # Número
            if not any(c.isdigit() for c in p1):
                raise forms.ValidationError("La contraseña debe contener al menos un número.")

            # Símbolo
            symbols = "!@#$%^&*()_+-={}[]|:;<>,.?/~`"
            if not any(c in symbols for c in p1):
                raise forms.ValidationError("La contraseña debe contener al menos un símbolo (!@#$...).")

            # Espacios no permitidos
            if " " in p1:
                raise forms.ValidationError("La contraseña no debe contener espacios.")

        return cleaned


class EditarPerfilForm(forms.ModelForm):
    """
    Formulario para editar datos del cliente (Nombre, Teléfono, Dirección).
    El correo se maneja con cuidado ya que está ligado al User.
    """
    email = forms.EmailField(label="Correo electrónico", required=True)

    class Meta:
        model = Cliente
        fields = ["nombre", "telefono", "direccion"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Estilizar campos
        for field in self.fields.values():
            field.widget.attrs.update({
                "class": "w-full px-4 py-3 rounded-xl border border-slate-200 focus:outline-none focus:ring-2 focus:ring-pirula-amber dark:bg-slate-900 dark:border-slate-700 dark:text-white"
            })

    def clean_email(self):
        # Validar que si cambia el email, no exista otro usuario con ese email
        email = self.cleaned_data.get("email")
        if self.instance.user:
            if User.objects.exclude(pk=self.instance.user.pk).filter(email=email).exists():
                 raise forms.ValidationError("Este correo ya está en uso por otro usuario.")
        return email


class ConvertirPedidoVentaForm(forms.Form):
    """
    Formulario para convertir un pedido en venta POS.
    Permite seleccionar el medio de pago y, si es efectivo, el monto recibido.
    """
    MEDIO_PAGO_CHOICES = [
        ("EFECTIVO", "💵 Efectivo"),
        ("DEBITO", "💳 Tarjeta Débito"),
        ("CREDITO", "💳 Tarjeta Crédito"),
        ("TRANSFERENCIA", "🏦 Transferencia"),
    ]
    
    DOC_TIPO_CHOICES = [
        ("BOLETA", "📄 Boleta"),
        ("FACTURA", "📋 Factura"),
        ("SIN_DOC", "📝 Sin documento"),
    ]
    
    medio_pago = forms.ChoiceField(
        choices=MEDIO_PAGO_CHOICES,
        initial="EFECTIVO",
        widget=forms.RadioSelect(attrs={
            "class": "h-4 w-4 text-pirula-accent border-pirula-beige focus:ring-pirula-accent"
        }),
        label="Medio de pago"
    )
    
    doc_tipo = forms.ChoiceField(
        choices=DOC_TIPO_CHOICES,
        initial="BOLETA",
        widget=forms.Select(attrs={
            "class": "w-full px-3 py-2 border border-pirula-beige rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-pirula-accent"
        }),
        label="Tipo de documento"
    )
    
    monto_recibido = forms.IntegerField(
        required=False,
        min_value=0,
        widget=forms.NumberInput(attrs={
            "class": "w-full px-4 py-3 text-xl font-bold text-center border-2 border-pirula-beige rounded-xl focus:outline-none focus:ring-2 focus:ring-pirula-accent focus:border-pirula-accent",
            "placeholder": "$ 0",
            "id": "monto_recibido"
        }),
        label="Monto recibido (efectivo)"
    )
    
    def __init__(self, *args, total_pedido=0, **kwargs):
        super().__init__(*args, **kwargs)
        self.total_pedido = total_pedido
    
    def clean(self):
        cleaned_data = super().clean()
        medio_pago = cleaned_data.get("medio_pago")
        monto_recibido = cleaned_data.get("monto_recibido")
        
        # Si es efectivo, validar monto recibido
        if medio_pago == "EFECTIVO":
            if not monto_recibido:
                raise forms.ValidationError({
                    "monto_recibido": "Debes ingresar el monto recibido para pagos en efectivo."
                })
            if monto_recibido < self.total_pedido:
                raise forms.ValidationError({
                    "monto_recibido": f"El monto recibido (${monto_recibido:,}) es menor al total (${self.total_pedido:,})."
                })
        
        return cleaned_data
    
    def get_vuelto(self):
        """Calcula el vuelto si es pago en efectivo."""
        if self.is_valid() and self.cleaned_data.get("medio_pago") == "EFECTIVO":
            monto_recibido = self.cleaned_data.get("monto_recibido", 0) or 0
            return max(monto_recibido - self.total_pedido, 0)
        return 0