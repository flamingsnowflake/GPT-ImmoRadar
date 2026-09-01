# HTTPS reverse proxy

GPT-ImmoRadar's browser-facing services are designed to listen on localhost and be exposed, when needed, through a separate HTTPS reverse proxy.

The reference deployment uses Apache, but nginx, Caddy or another reverse proxy can provide the same boundary.

## Request path

```text
Tampermonkey in the user's browser
        |
        | HTTPS
        v
reverse proxy :443
        |
        +-- /browser-enrich
        |      -> http://127.0.0.1:8765/enrich
        |
        +-- /immobilien-energy/energy
               -> http://127.0.0.1:8090/energy
```

The application-level tokens are still required. TLS/reverse proxying does not replace authentication.

## Recommended properties

A public deployment should:

- use TLS for browser-to-server traffic;
- expose only the required application routes;
- keep application listeners on localhost/private interfaces;
- allow only the HTTP methods that are actually needed;
- set reasonable request-body limits and timeouts;
- avoid logging sensitive request bodies;
- return a default deny/404 response for unrelated paths if the host is API-only.

## Apache example

A generic example is provided at:

```text
deploy/apache/immoradar.example.conf
```

Replace the example hostname and certificate paths with values from your own deployment before enabling it.

Validate Apache configuration before reloading:

```bash
sudo apache2ctl configtest
```

Then:

```bash
sudo systemctl reload apache2
```

## Security headers

Because these routes are API endpoints rather than web pages, restrictive response headers are appropriate. The example configuration demonstrates HSTS, `nosniff`, frame denial, a restrictive referrer policy and a minimal Content-Security-Policy.

## Certificates

Certificate and private-key material is runtime secret material. Never commit it to the repository.

Let's Encrypt/Certbot is one option; any properly managed TLS certificate is acceptable.

## Tampermonkey

The public userscript intentionally contains an invalid example endpoint. Configure the userscript for your own HTTPS hostname before use and enter your own API tokens at runtime.

Do not point a fork at another operator's server.
