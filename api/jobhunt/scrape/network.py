"""Skip scraping when a corporate proxy is re-signing TLS."""

import os
import socket
import ssl


def corporate_network(host: str = "www.linkedin.com") -> bool:
    """True when the certificate is not one certifi trusts.

    ``JOBHUNT_ALLOW_CORP_NETWORK=1`` is for tests. It is not set in ``.env``.
    """
    if os.environ.get("JOBHUNT_ALLOW_CORP_NETWORK") == "1":
        return False
    context = ssl.create_default_context()
    try:
        with socket.create_connection((host, 443), timeout=8) as sock:
            with context.wrap_socket(sock, server_hostname=host) as tls:
                tls.getpeercert()
    except ssl.SSLCertVerificationError:
        return True
    return False
