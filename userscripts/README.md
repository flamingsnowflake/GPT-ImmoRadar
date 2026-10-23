# Browser userscript 1.3.7

Install [Immobilienmonitor – Browser & Energie](https://raw.githubusercontent.com/flamingsnowflake/GPT-ImmoRadar/main/userscripts/immobilienmonitor-browser-energy.user.js) in Tampermonkey or Violentmonkey. The legacy filename `immobilien-energy.user.js` contains the same release.

## One-time setup

1. Open an ImmoScout24 or Immowelt exposé.
2. Click **⚙ → S** and enter your monitor's HTTPS base address, including a custom port if needed, for example `https://monitor.example.org:8443`. Do not include `/browser-enrich` or another path. You can also use **Monitor-Server einstellen** in the userscript manager's menu.
3. Click **⚙ → B** to enter your browser-enrichment token. Set **⚙ → E** for the separate Energy API token, if used.
4. Allow connections to your chosen server when the userscript manager asks.

Server address and tokens are stored in the userscript manager's storage. No listing data or tokens are sent until a valid server address is configured. The public installer has no production server or token embedded. Changing to a different server asks for confirmation and clears both tokens to prevent sending the old credentials to that server.

The `@connect *` permission accommodates self-hosted servers; the script sends requests only to the HTTPS origin selected in its settings.

## Updates

The script checks its GitHub `.meta.js` update URL and downloads releases from the canonical `.user.js` URL. Enable automatic script updates in your userscript manager, or use its **Check for updates** action. Future releases retain the same name, namespace, server storage key and token storage keys.

Updates of the existing public version preserve its identity. A manually installed private deployment may use a different namespace: disable that old copy before installing this public version, and configure its server and tokens once. Keep only one copy enabled on a page.

## Browser support and workflow

- ImmoScout24 and Immowelt root domains and subdomains.
- Browser enrichment, SPA navigation detection, CAPTCHA pause and the manual Energy fallback.
- Firefox/Fennec content-mode injection and mobile panel placement above portal controls.
- Tokens are requested through the settings button rather than timer-triggered prompts.
- Contributors use only their own token and the scope granted by their monitor administrator.

On Android, reopen the browser after replacing an old release. If using private browsing, allow the userscript manager in private tabs.

## Validation

Run the configuration and update-metadata regression tests with Node.js:

```bash
node --test userscripts/tests/configuration.test.cjs
```

Historical ZIP files under `archive/` are older releases. Use the canonical GitHub installer for current updates.
