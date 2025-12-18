import os
import resend
from django.conf import settings
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
    
    # En desarrollo o si SITE_URL no está configurado, usar un placeholder
    # o simplemente retornar vacío para que no se muestre imagen rota
    return ""


from django.core.mail import send_mail
from django.utils.html import strip_tags

def _enviar_email_resend(destinatario, subject, template_html, template_txt, context):
    """Envía email usando el backend configurado en Django (SMTP/Resend/etc)."""
    if not destinatario:
        return

    context = {
        **context,
        "subject": subject,
        "logo_url": _get_logo_url(),
    }

    cuerpo_html = render_to_string(template_html, context)
    cuerpo_txt = render_to_string(template_txt, context)

    # Si no hay cuerpo de texto, lo generamos del HTML
    if not cuerpo_txt:
        cuerpo_txt = strip_tags(cuerpo_html)

    try:
        # Usamos send_mail de Django que respeta EMAIL_BACKEND
        send_mail(
            subject=subject,
            message=cuerpo_txt,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[destinatario],
            html_message=cuerpo_html,
            fail_silently=False,
        )
        print(f"✅ Email enviado exitosamente a {destinatario}")
    except Exception as e:
        print(f"❌ Error al enviar email a {destinatario}: {e}")
        raise


def enviar_correo_pedido_creado(pedido):
    subject = f"El Gran Pirula - Pedido recibido ({pedido.codigo})"
    _enviar_email_resend(
        destinatario=pedido.correo,
        subject=subject,
        template_html="emails/pedido_creado.html",
        template_txt="emails/pedido_creado.txt",
        context={"pedido": pedido},
    )


def enviar_correo_cambio_estado(pedido):
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

    _enviar_email_resend(
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
