"""Email validation policy.

Pydantic's `EmailStr` uses email-validator, which rejects reserved TLDs such as `.test`. Local
dev users, Keycloak seed users and the demo corpus all use `@acme.test` / `@globex.test`, so local
and test environments allow `.test`; staging and production keep rejecting it. Changing the
library's list is the approach its README documents.
"""

import email_validator

from app.core.config import Environment, Settings

_DEV_DOMAINS = {"test"}


def configure_email_validation(settings: Settings) -> None:
    if settings.environment in {Environment.LOCAL, Environment.TEST}:
        email_validator.SPECIAL_USE_DOMAIN_NAMES[:] = [
            d for d in email_validator.SPECIAL_USE_DOMAIN_NAMES if d not in _DEV_DOMAINS
        ]
