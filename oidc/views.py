from __future__ import absolute_import, print_function

import logging

from sentry.auth.view import AuthView, ConfigureView
from sentry.utils import json
from sentry.utils.signing import urlsafe_b64decode
from six.moves import map as _map

from .constants import ERR_INVALID_RESPONSE, ISSUER, ERR_INVALID_DOMAIN, OIDC_DOMAIN_ALLOWLIST, OIDC_DOMAIN_BLOCKLIST

logger = logging.getLogger("sentry.auth.oidc")


def map(a, b, *c):
    return list(_map(a, b, *c))


class FetchUser(AuthView):
    def __init__(self, domains, version, *args, **kwargs):
        self.domains = domains
        self.version = version
        super(FetchUser, self).__init__(*args, **kwargs)

    def dispatch(self, request, helper):
        data = helper.fetch_state("data")

        try:
            id_token = data["id_token"]
        except KeyError:
            logger.error("Missing id_token in OAuth response: %s" % data)
            return helper.error(ERR_INVALID_RESPONSE)

        try:
            _, payload, _ = map(urlsafe_b64decode, id_token.split(".", 2))
        except Exception as exc:
            logger.error(u"Unable to decode id_token: %s" % exc, exc_info=True)
            return helper.error(ERR_INVALID_RESPONSE)

        try:
            payload = json.loads(payload)
        except Exception as exc:
            logger.error(u"Unable to decode id_token payload: %s" % exc, exc_info=True)
            return helper.error(ERR_INVALID_RESPONSE)

        if not payload.get("email"):
            logger.error("Missing email in id_token payload: %s" % id_token)
            return helper.error(ERR_INVALID_RESPONSE)

        # support legacy style domains with pure domain regexp
        if self.version is None:
            domain = extract_domain(payload["email"])
        else:
            domain = payload.get("hd")

        if domain is None:
            return helper.error(ERR_INVALID_DOMAIN % (domain,))

        if domain in OIDC_DOMAIN_BLOCKLIST:
            return helper.error(ERR_INVALID_DOMAIN % (domain,))

        if OIDC_DOMAIN_ALLOWLIST != set() and domain not in OIDC_DOMAIN_ALLOWLIST:
            return helper.error(ERR_INVALID_DOMAIN % (domain,))

        logger.info("User domain: %s" % domain)
        helper.bind_state("domain", domain)
        helper.bind_state("user", payload)

        return helper.next_step()


class OIDCConfigureView(ConfigureView):
    def dispatch(self, request, organization, auth_provider):
        config = auth_provider.config
        if config.get("domain"):
            domains = [config["domain"]]
        else:
            domains = config.get("domains")
        return self.render(
            "oidc/configure.html",
            {"provider_name": ISSUER or "", "domains": domains or []},
        )


def extract_domain(email):
    return email.rsplit("@", 1)[-1]
