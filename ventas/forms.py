from django import forms
from django.forms import inlineformset_factory
from .models import Venta, VentaItem


class VentaForm(forms.ModelForm):
    class Meta:
        model = Venta
        fields = ["doc_tipo", "doc_num", "medio_pago", "comentario"]


VentaItemFormSet = inlineformset_factory(
    parent_model=Venta,
    model=VentaItem,
    fields=["producto", "cantidad", "precio_unit"],
    extra=10,          # hasta 10 productos en una venta
    can_delete=True,   # servirá cuando tengamos edición
)
