# core/templatetags/form_extras.py
from django import template

register = template.Library()

@register.filter(name="add_class")
def add_class(field, css):
    """
    Permite hacer:
        {{ form.campo|add_class:"clases css" }}
    conservando las clases que ya tenga el widget.
    """
    existing_classes = field.field.widget.attrs.get("class", "")
    new_classes = (existing_classes + " " + css).strip()
    return field.as_widget(attrs={**field.field.widget.attrs, "class": new_classes})
