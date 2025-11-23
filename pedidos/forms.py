from django import forms
from django.forms import inlineformset_factory

from .models import Pedido, PedidoItem, Cliente
from inventario.models import Producto


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
