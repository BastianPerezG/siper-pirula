from django import forms
from .models import Producto, MovimientoInventario

class ProductoCrearForm(forms.ModelForm):
    class Meta:
        model = Producto
        fields = ["ean", "nombre", "categoria", "precio", "costo", "stock_min", "ubicacion", "activo"]
        widgets = {
            "ean": forms.TextInput(attrs={"readonly": "readonly"}),
        }


class MovimientoCrearForm(forms.ModelForm):
    class Meta:
        model = MovimientoInventario
        fields = ["tipo", "cantidad", "comentario"]