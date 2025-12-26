"""
Módulo de emails para pedidos usando Django's email backend (SMTP).
"""
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string


def _get_logo_url():
    """
    Obtiene la URL del logo para emails.
    En producción usa SITE_URL, en desarrollo usa un placeholder.
    """
    base = getattr(settings, "SITE_URL", "")
    
    # Si tenemos SITE_URL configurado (producción), usar la URL del logo
    if base and "localhost" not in base and "127.0.0.1" not in base:
        return f"{base}/static/img/logo_gran_pirula_marron.jpg"
    
    # En desarrollo o si SITE_URL no está configurado
    return ""


def _enviar_email(destinatario, subject, template_html, template_txt, context):
    """
    Envía email usando el backend SMTP de Django.
    Configurado para usar Gmail en settings.py.
    """
    if not destinatario:
        print("⚠️ No hay destinatario para el email")
        return
    
    # Verificar configuración
    if not settings.EMAIL_HOST_USER:
        print("⚠️ EMAIL_HOST_USER no configurado. Email no enviado.")
        return

    # Agregar datos comunes al contexto
    context = {
        **context,
        "subject": subject,
        "logo_url": _get_logo_url(),
    }

    # Renderizar templates
    try:
        cuerpo_html = render_to_string(template_html, context)
        cuerpo_txt = render_to_string(template_txt, context)
    except Exception as e:
        print(f"❌ Error al renderizar templates: {e}")
        return

    # Preparar el email - usar DEFAULT_FROM_EMAIL para el remitente visible
    from_email = settings.DEFAULT_FROM_EMAIL
    
    try:
        email = EmailMultiAlternatives(
            subject=subject,
            body=cuerpo_txt,
            from_email=from_email,
            to=[destinatario],
        )
        email.attach_alternative(cuerpo_html, "text/html")
        
        # Enviar
        email.send(fail_silently=False)
        print(f"✅ Email enviado exitosamente a {destinatario}")
        return True
        
    except Exception as e:
        print(f"❌ Error al enviar email a {destinatario}: {e}")
        # No relanzamos para no romper el flujo principal
        return False


def enviar_correo_pedido_creado(pedido):
    """Envía correo de confirmación cuando se crea un pedido."""
    if not pedido.correo:
        print(f"⚠️ Pedido {pedido.codigo} sin correo, no se envía notificación")
        return
    
    subject = f"El Gran Pirula - Pedido recibido ({pedido.codigo})"
    
    _enviar_email(
        destinatario=pedido.correo,
        subject=subject,
        template_html="emails/pedido_creado.html",
        template_txt="emails/pedido_creado.txt",
        context={"pedido": pedido},
    )


def enviar_correo_cambio_estado(pedido):
    """Envía correo cuando cambia el estado de un pedido."""
    if not pedido.correo:
        return

    try:
        estado_display = pedido.get_estado_display()
    except Exception:
        estado_display = str(pedido.estado)

    try:
        es_listo = pedido.estado == pedido.EST_LISTO
    except AttributeError:
        es_listo = (str(pedido.estado).upper() == "LISTO")

    subject = (
        f"El Gran Pirula - Tu pedido {pedido.codigo} está LISTO para retirar"
        if es_listo
        else f"El Gran Pirula - Actualización de tu pedido ({pedido.codigo})"
    )

    _enviar_email(
        destinatario=pedido.correo,
        subject=subject,
        template_html="emails/pedido_cambio_estado.html",
        template_txt="emails/pedido_cambio_estado.txt",
        context={
            "pedido": pedido,
            "estado_display": estado_display,
            "es_listo": es_listo,
        },
    )
