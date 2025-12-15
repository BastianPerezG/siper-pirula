import os
import resend
from django.conf import settings
from django.template.loader import render_to_string


def _get_logo_url():
    base = getattr(settings, "SITE_URL", "http://localhost:8000")
    return f"{base}{settings.STATIC_URL}img/logo_gran_pirula_marron.jpg"


def _enviar_email_resend(destinatario, subject, template_html, template_txt, context):
    """Envía email usando Resend API."""
    if not destinatario:
        return

    # Configurar API key
    resend.api_key = os.environ.get("RESEND_API_KEY", "")
    
    if not resend.api_key:
        print(f"⚠️ RESEND_API_KEY no configurada. Email no enviado a {destinatario}")
        return

    context = {
        **context,
        "subject": subject,
        "logo_url": _get_logo_url(),
    }

    cuerpo_html = render_to_string(template_html, context)
    cuerpo_txt = render_to_string(template_txt, context)

    # En desarrollo, enviar siempre al correo del desarrollador (limitación de Resend gratuito)
    dev_email = os.environ.get("DEV_EMAIL", "")
    email_destino = dev_email if dev_email else destinatario
    
    if dev_email and dev_email != destinatario:
        print(f"📧 [DEV MODE] Redirigiendo email de {destinatario} → {dev_email}")

    try:
        params = {
            "from": "El Gran Pirula <onboarding@resend.dev>",  # Dominio de prueba de Resend
            "to": [email_destino],
            "subject": subject,
            "html": cuerpo_html,
            "text": cuerpo_txt,
        }
        
        response = resend.Emails.send(params)
        print(f"✅ Email enviado a {email_destino}: {response}")
        return response
        
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
