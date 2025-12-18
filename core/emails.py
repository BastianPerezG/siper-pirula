import os
import resend
from django.conf import settings
from django.template.loader import render_to_string
from django.core.mail import send_mail
from django.utils.html import strip_tags
def _get_logo_url():
    base = getattr(settings, "SITE_URL", "http://localhost:8000")
    return f"{base}{settings.STATIC_URL}img/logo_gran_pirula_marron.jpg"




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
        # y DEFAULT_FROM_EMAIL (que debería ser scastrof2020@gmail.com)
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
