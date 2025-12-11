# core/templatetags/core_log_tags.py

from django import template
from django.template.loader import select_template

register = template.Library()

@register.inclusion_tag('core/log_templates/render_log_entry.html', takes_context=True)
def render_log_entry(context, log_entry):
    """
    Decide qué plantilla específica usar para renderizar el log.
    
    Patrón de búsqueda: log_{action_type}_{model_name}.html
    """
    
    # 1. Normalizar nombres
    action_type = log_entry.tipo_accion.lower() 
    model_name = log_entry.nombre_modelo.lower().replace('_', '').replace(' ', '') 

    # 2. Definir candidatos de plantilla
    specific_template = f'log_{model_name}.html'
    generic_template = f'log_{action_type}.html'
    default_template = 'log_default.html'
    
    # Rutas completas dentro de templates/core/log_templates/
    template_candidates = [
        f'core/log_templates/{specific_template}',
        f'core/log_templates/{generic_template}',
        f'core/log_templates/{default_template}',
    ]
    
    # 3. Seleccionar la plantilla existente
    try:
        # select_template encuentra el primer archivo que existe
        selected_template = select_template(template_candidates)
        template_name_to_use = selected_template.template.name
    except Exception:
        # Fallback al default si nada existe
        template_name_to_use = f'core/log_templates/{default_template}'

    return {
        'log': log_entry,
        # La plantilla que render_log_entry.html debe incluir
        'template_to_include': template_name_to_use, 
    }