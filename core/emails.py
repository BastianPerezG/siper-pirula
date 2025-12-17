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
    resend.api_key = getattr(settings, "RESEND_API_KEY", "")
    
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
        # No relanzamos para no romper el flujo principal si falla el email,
        # pero para debugging es útil saberlo.
        raise


def enviar_correo_restablecer_password(usuario, reset_url, uid, token):
    """
    Envía el correo de restablecimiento de contraseña usando Resend.
    """
    subject = "Restablecer contraseña - El Gran Pirula"
    
    context = {
        "user": usuario,
        "reset_url": reset_url,
        "uid": uid,
        "uidb64": uid,  # Alias para compatibilidad con algunas plantillas
        "token": token,
    }
    
    print(f"📧 [DEBUG EMAIL] Preparando correo para {usuario.email}")
    print(f"🔗 URL: {reset_url}")
    print(f"🆔 UID: {uid}")
    
    _enviar_email_resend(
        destinatario=usuario.email,
        subject=subject,
        template_html="registration/password_reset_email_html.html", # Plantilla HTML bonita
        template_txt="registration/password_reset_email.html",       # Plantilla Texto Plano
        context=context,
    )
