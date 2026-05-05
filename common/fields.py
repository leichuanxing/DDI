from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.db import models


class EncryptedTextField(models.TextField):
    description = 'Encrypted text field for sensitive component configuration'

    def _fernet(self):
        key = settings.CONFIG_ENCRYPTION_KEY
        if not key:
            return None
        return Fernet(key.encode())

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        f = self._fernet()
        if value and f and not str(value).startswith('gAAAA'):
            return f.encrypt(str(value).encode()).decode()
        return value

    def from_db_value(self, value, expression, connection):
        f = self._fernet()
        if value and f:
            try:
                return f.decrypt(value.encode()).decode()
            except InvalidToken:
                return value
        return value
