from django.core.mail.backends.smtp import EmailBackend
from django.conf import settings
import ssl

class smtpInseguroBackend(EmailBackend):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if settings.DEBUG:
            context_inseguro = ssl.create_default_context()
            context_inseguro.check_hostname = False
            context_inseguro.verify_mode = ssl.CERT_NONE
            self.ssl_context = context_inseguro