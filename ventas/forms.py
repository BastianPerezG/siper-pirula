from django import forms
from django.forms import inlineformset_factory
from .models import Venta, VentaItem
from inventario.models import Producto


# Forms de Ventas


class VentaForm(forms.ModelForm):
    class Meta:
        model = Venta
        fields = ["doc_tipo", "doc_num", "medio_pago", "comentario"]
    # el campo negocio NO se muestra, se setea en la vista


class VentaItemForm(forms.ModelForm):
    class Meta:
        model = VentaItem
        fields = ["producto", "cantidad", "precio_unit"]

    def __init__(self, *args, negocio=None, **kwargs):
        super().__init__(*args, **kwargs)
        qs = Producto.objects.filter(activo=True)
        if negocio is not None:
            qs = qs.filter(negocio=negocio)
        self.fields["producto"].queryset = qs
        # Sólo lectura: se completa solo
        self.fields["precio_unit"].widget.attrs["readonly"] = True


VentaItemFormSet = inlineformset_factory(
    Venta,
    VentaItem,
    form=VentaItemForm,
    extra=3,
    can_delete=True,
)