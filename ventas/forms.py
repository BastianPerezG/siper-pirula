from django import forms
from django.forms import inlineformset_factory
from .models import Venta, VentaItem
from inventario.models import Producto


class VentaForm(forms.ModelForm):
    class Meta:
        model = Venta
        fields = ["doc_tipo", "doc_num", "medio_pago", "comentario"]

class VentaItemForm(forms.ModelForm):
    class Meta:
        model = VentaItem
        fields = ["producto", "cantidad", "precio_unit"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Sólo productos activos
        self.fields["producto"].queryset = Producto.objects.filter(activo=True)

        # El precio lo rellenamos por JS y por backend → no obligatorio en POST
        self.fields["precio_unit"].required = False
        self.fields["precio_unit"].widget.attrs["readonly"] = True

    def clean(self):
        """
        Si hay producto, fijamos el precio_unit desde el producto
        (por seguridad, aunque el usuario toque el HTML).
        """
        cleaned = super().clean()
        producto = cleaned.get("producto")

        if producto is not None:
            cleaned["precio_unit"] = producto.precio

        return cleaned


VentaItemFormSet = inlineformset_factory(
    Venta,
    VentaItem,
    form=VentaItemForm,
    extra=3,
    can_delete=True,
)