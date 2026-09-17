// ==UserScript==
// @name         Immobilienmonitor – Browser & Energie
// @namespace    https://example.invalid/immoradar/
// @version      1.3.3
// @description  Sendet Browserdaten inklusive Energie-DOM-Hinweisen automatisch an den Immobilienmonitor; manueller Energieversand bleibt als Fallback.
// @match        https://www.immobilienscout24.de/expose/*
// @match        https://www.immowelt.de/expose/*
// @grant        GM_xmlhttpRequest
// @grant        GM_getValue
// @grant        GM_setValue
// @connect      monitor.example.invalid
// @inject-into  content
// @run-at       document-idle
// ==/UserScript==

(function () {
    "use strict";

    const API_URL = "https://monitor.example.invalid/immobilien-energy/energy";
    const TOKEN_KEY = "immobilien_energy_api_token";

    const BROWSER_API_URL =
        "https://monitor.example.invalid/browser-enrich";

    const BROWSER_TOKEN_KEY =
        "immobilien_browser_enrich_token";

    const BROWSER_MAX_ATTEMPTS = 3;

    let browserFinished = false;
    let browserSending = false;
    let browserAttempts = 0;
    let browserCheckInterval = null;
    let browserObjectKey = null;
    let browserRouteInterval = null;
    let browserRouteChangedAt = 0;
    let browserPreparationKey = null;
    let browserPreparationPromise = null;
    let browserOpenedEnergyDetails = false;

    function clean(value) {
        if (value == null) {
            return null;
        }

        const text = String(value)
            .replace(/\u00a0/g, " ")
            .replace(/[ \t]+/g, " ")
            .trim();

        return text || null;
    }

    function pageLines() {
        return (document.body?.innerText || "")
            .replace(/\r/g, "")
            .split(/\n+/)
            .map(clean)
            .filter(Boolean);
    }

    function portalInfo() {
        const host = location.hostname.toLowerCase();
        const path = location.pathname;

        if (host.endsWith("immobilienscout24.de")) {
            const match = path.match(
                /\/expose\/(\d+)/i
            );

            return match
                ? {
                    portal: "immoscout24",
                    portalId: match[1],
                }
                : null;
        }

        if (host.endsWith("immowelt.de")) {
            const match = path.match(
                /\/expose\/([A-Za-z0-9-]+)/i
            );

            return match
                ? {
                    portal: "immowelt",
                    portalId: match[1].toLowerCase(),
                }
                : null;
        }

        return null;
    }

    function portalKey(info) {
        if (!info) {
            return null;
        }

        return `${info.portal}:${info.portalId}`;
    }

    function payloadMatchesCurrentObject(payload) {
        const info = portalInfo();

        return Boolean(
            info
            && payload
            && info.portal === payload.portal
            && info.portalId === payload.portal_id
        );
    }

    function startBrowserCheckCycle(delay = 0) {
        browserFinished = false;
        browserSending = false;
        browserAttempts = 0;

        if (browserCheckInterval) {
            window.clearInterval(
                browserCheckInterval
            );

            browserCheckInterval = null;
        }

        if (delay > 0) {
            window.setTimeout(
                checkBrowserEnrichment,
                delay
            );
        } else {
            checkBrowserEnrichment();
        }

        browserCheckInterval =
            window.setInterval(
                checkBrowserEnrichment,
                2000
            );
    }

    function checkPortalNavigation() {
        const info = portalInfo();
        const key = portalKey(info);

        if (!key) {
            return;
        }

        if (browserObjectKey === null) {
            browserObjectKey = key;
            return;
        }

        if (key === browserObjectKey) {
            return;
        }

        browserObjectKey = key;
        browserRouteChangedAt = Date.now();

        // Ein Energie-Dialog gehört immer zum alten Exposé.
        removeModal();

        showBrowserStatus(
            "🏠 Monitor: neues Exposé – prüfe Seite …",
            "working"
        );

        // SPA-Seiten lassen URL und Inhalt nicht zwingend exakt
        // gleichzeitig wechseln. Kurz warten, bevor Seitentext
        // unter der neuen Exposé-ID übertragen wird.
        startBrowserCheckCycle(1500);
    }

    function extractEnergySection(lines) {
        const startPatterns = [
            /^Bausubstanz\s*&\s*Energieausweis$/i,
            /^Bausubstanz\s+und\s+Energie$/i,
        ];

        const endPatterns = [
            /^Beschreibung$/i,
            /^Preisdetails$/i,
            /^Lage$/i,
            /^Weitere Informationen$/i,
            /^Kosten$/i,
        ];

        const start = lines.findIndex((line) =>
            startPatterns.some((pattern) => pattern.test(line))
        );

        if (start < 0) {
            return [];
        }

        const result = [];

        for (let i = start + 1; i < lines.length && result.length < 60; i += 1) {
            const line = lines[i];

            if (
                result.length > 0
                && endPatterns.some((pattern) => pattern.test(line))
            ) {
                break;
            }

            result.push(line);
        }

        return result;
    }

    function valueAfterLabel(lines, labels) {
        const normalizedLabels = labels.map((label) => label.toLowerCase());

        for (let i = 0; i < lines.length; i += 1) {
            const line = lines[i];
            const lower = line.toLowerCase();

            for (let j = 0; j < normalizedLabels.length; j += 1) {
                const label = normalizedLabels[j];

                if (lower === label) {
                    return clean(lines[i + 1]);
                }

                if (lower.startsWith(`${label}:`)) {
                    return clean(line.slice(label.length + 1));
                }

                if (lower.startsWith(`${label} `)) {
                    return clean(line.slice(label.length + 1));
                }
            }
        }

        return null;
    }

    function firstRegex(text, patterns) {
        for (const pattern of patterns) {
            const match = text.match(pattern);

            if (match) {
                return clean(match[1]);
            }
        }

        return null;
    }

    function normalizeNumber(value) {
        if (!value) {
            return null;
        }

        const normalized = value
            .replace(/\s/g, "")
            .replace(/\.(?=\d{3}(?:\D|$))/g, "")
            .replace(",", ".");

        const number = Number(normalized);

        return Number.isFinite(number) ? number : null;
    }

    function normalizeEnergyText(text) {
        return String(text || "")
            .replace(/\u00a0/g, " ")
            .replace(
                /Energie-\s*ausweistyp/gi,
                "Energieausweistyp"
            )
            .replace(
                /Endenergie-\s*bedarf/gi,
                "Endenergiebedarf"
            )
            .replace(
                /Endenergie-\s*verbrauch/gi,
                "Endenergieverbrauch"
            )
            .replace(
                /Energieeffizienz-\s*klasse/gi,
                "Energieeffizienzklasse"
            )
            .replace(
                /Wesentliche\s+Energieträger/gi,
                "Wesentliche Energieträger"
            )
            .replace(
                /Wesentlicher\s+Energieträger/gi,
                "Wesentlicher Energieträger"
            )
            .replace(
                /Baujahr laut\s+Energieausweis/gi,
                "Baujahr laut Energieausweis"
            );
    }

    function extractEnergyClassFromDom() {
        const images = document.querySelectorAll(
            'img[src*="energyEfficiencyClass"]'
        );

        for (const image of images) {
            const value = clean(
                image.getAttribute("alt")
            );

            if (
                value
                && /^[A-H](?:\+)?$/i.test(value)
            ) {
                return value.toUpperCase();
            }
        }

        return null;
    }

    async function prepareImmoweltEnergyDetails() {
        const info = portalInfo();

        if (
            !info
            || info.portal !== "immowelt"
        ) {
            return;
        }

        const buttons = [
            ...document.querySelectorAll(
                "button, a"
            )
        ];

        const moreInfoButton =
            buttons.find((element) => {
                const text = clean(
                    element.textContent
                );

                return (
                    text
                    && /^Mehr Infos$/i.test(
                        text
                    )
                );
            });

        if (!moreInfoButton) {
            return;
        }

        moreInfoButton.click();
        browserOpenedEnergyDetails = true;

        for (
            let attempt = 0;
            attempt < 20;
            attempt += 1
        ) {
            await new Promise(
                (resolve) =>
                    window.setTimeout(
                        resolve,
                        100
                    )
            );

            const text =
                document.body?.innerText
                || "";

            if (
                /Energieausweistyp/i.test(
                    text
                )
                && (
                    /Energieverbrauch/i.test(
                        text
                    )
                    || /Endenergiebedarf/i.test(
                        text
                    )
                )
            ) {
                return;
            }
        }
    }

    function closeAutoOpenedEnergyDetails() {
        if (!browserOpenedEnergyDetails) {
            return;
        }

        browserOpenedEnergyDetails = false;

        const dialogs = [
            ...document.querySelectorAll(
                '[role="dialog"], [aria-modal="true"]'
            )
        ];

        const dialog = dialogs.find((element) => {
            const text = clean(
                element.innerText
                || element.textContent
            );

            return Boolean(
                text
                && /Bausubstanz|Energieausweis/i.test(
                    text
                )
            );
        });

        if (dialog) {
            const closeButton = [
                ...dialog.querySelectorAll(
                    'button, [role="button"]'
                )
            ].find((element) => {
                const label = clean(
                    element.getAttribute(
                        'aria-label'
                    )
                    || element.getAttribute(
                        'title'
                    )
                    || element.textContent
                );

                return Boolean(
                    label
                    && /^(schließen|close|x)$/i.test(
                        label
                    )
                );
            });

            if (closeButton) {
                closeButton.click();
                return;
            }
        }

        document.dispatchEvent(
            new KeyboardEvent(
                'keydown',
                {
                    key: 'Escape',
                    code: 'Escape',
                    bubbles: true,
                }
            )
        );
    }

    async function prepareBrowserForEnrichment(info) {
        const key = portalKey(info);

        if (!key) {
            return;
        }

        if (browserPreparationKey === key) {
            return;
        }

        if (browserPreparationPromise) {
            await browserPreparationPromise;

            if (browserPreparationKey === key) {
                return;
            }
        }

        const preparationKey = key;

        browserPreparationPromise = (
            async () => {
                if (info.portal === "immowelt") {
                    await prepareImmoweltEnergyDetails();
                }

                const currentInfo = portalInfo();

                if (
                    currentInfo
                    && portalKey(currentInfo) === preparationKey
                ) {
                    browserPreparationKey =
                        preparationKey;
                }
            }
        )();

        try {
            await browserPreparationPromise;
        } finally {
            browserPreparationPromise = null;
        }
    }

    function extractEnergyData() {
        const lines = pageLines();
        const fullText = lines.join("\n");
        const section = extractEnergySection(lines);
        const sectionText = section.join("\n");
        const preferredText = normalizeEnergyText(sectionText || fullText);
        const normalizedFullText = normalizeEnergyText(fullText);

        let energyClass = extractEnergyClassFromDom();

        if (!energyClass) {
            energyClass = firstRegex(
                normalizedFullText,
                [/Energieeffizienz[\s\u00ad\u2010\u2011\u2012\u2013\u2014-]*klasse\s*:?\s*([A-H](?:\+)?)/i]
            );
        }

        if (!energyClass && section.length) {
            const energyHeadingIndex = section.findIndex((line) => /^Energieausweis$/i.test(line));
            if (energyHeadingIndex >= 0) {
                for (let i = energyHeadingIndex + 1; i < Math.min(section.length, energyHeadingIndex + 6); i += 1) {
                    const match = section[i].match(/^([A-H](?:\+)?)$/i);
                    if (match) {
                        energyClass = match[1];
                        break;
                    }
                }
            }
        }

        if (energyClass) {
            energyClass = energyClass.trim().toUpperCase();
        }

        const energyValueText = firstRegex(
            normalizedFullText,
            [
                /Endenergie[\s\u00ad\u2010\u2011\u2012\u2013\u2014-]*(?:bedarf|verbrauch)\s*:?\s*([0-9]{1,4}(?:[.,][0-9]{1,2})?)/i,
                /Energieverbrauch\s*:?\s*([0-9]{1,4}(?:[.,][0-9]{1,2})?)/i,
            ]
        );

        const energyValue = normalizeNumber(energyValueText);
        let certificateType = "unknown";

        if (/Energieausweistyp\s*:?\s*Bedarfsausweis/i.test(preferredText) || /\bBedarfsausweis\b/i.test(preferredText)) {
            certificateType = "demand";
        } else if (/Energieausweistyp\s*:?\s*Verbrauchsausweis/i.test(preferredText) || /\bVerbrauchsausweis\b/i.test(preferredText)) {
            certificateType = "consumption";
        } else if (/\bBedarfsausweis\b/i.test(normalizedFullText)) {
            certificateType = "demand";
        } else if (/\bVerbrauchsausweis\b/i.test(normalizedFullText)) {
            certificateType = "consumption";
        }

        let certificateStatus = "unknown";

        if (/Energieausweis[\s\S]{0,120}(?:laut Gesetz )?nicht erforderlich/i.test(normalizedFullText) || /(?:laut Gesetz )?nicht erforderlich[\s\S]{0,120}Energieausweis/i.test(normalizedFullText)) {
            certificateStatus = "not_required";
        } else if (/Energieausweis[\s\S]{0,120}(?:noch nicht|nicht verfügbar|nicht vorhanden)/i.test(normalizedFullText)) {
            certificateStatus = "not_available_yet";
        } else if (energyClass || energyValue !== null || certificateType !== "unknown" || /Energieausweis\s*:?\s*liegt vor/i.test(normalizedFullText)) {
            certificateStatus = "available";
        }

        let heatingType = firstRegex(preferredText, [/Heizungsart\s*:?\s*([^\n]{1,120})/i]);
        if (!heatingType) {
            heatingType = valueAfterLabel(section, ["Heizungsart"]);
        }
        if (!heatingType) {
            heatingType = firstRegex(normalizedFullText, [/Heizungsart\s*:?\s*([^\n]{1,120})/i]);
        }

        let energySource = firstRegex(
            preferredText,
            [/(?:Wesentliche Energieträger|Wesentlicher Energieträger|Hauptenergieträger|Energieträger)\s*:?\s*([^\n]{1,120})/i]
        );
        if (!energySource) {
            energySource = valueAfterLabel(section, ["Energieträger", "Wesentliche Energieträger", "Wesentlicher Energieträger", "Hauptenergieträger"]);
        }
        if (!energySource) {
            energySource = firstRegex(normalizedFullText, [/(?:Wesentliche Energieträger|Wesentlicher Energieträger|Hauptenergieträger|Energieträger)\s*:?\s*([^\n]{1,120})/i]);
        }

        let yearText = firstRegex(
            preferredText,
            [
                /Baujahr laut Energieausweis\s*:?\s*((?:18|19|20)\d{2})/i,
                /Baujahr des Objekts lt\. Energieausweis(?: ist)?\s*:?\s*((?:18|19|20)\d{2})/i,
            ]
        );
        if (!yearText) {
            yearText = valueAfterLabel(section, ["Baujahr laut Energieausweis", "Baujahr Gebäude (Ursprung)", "Baujahr"]);
        }
        if (!yearText) {
            yearText = firstRegex(
                normalizedFullText,
                [
                    /Baujahr laut Energieausweis\s*:?\s*((?:18|19|20)\d{2})/i,
                    /Baujahr des Objekts lt\. Energieausweis(?: ist)?\s*:?\s*((?:18|19|20)\d{2})/i,
                ]
            );
        }

        const yearMatch = yearText && String(yearText).match(/\b(?:18|19|20)\d{2}\b/);
        const constructionYear = yearMatch ? Number(yearMatch[0]) : null;

        if (certificateStatus === "not_required") {
            energyClass = null;
        }

        const rawCandidates = [];
        if (section.length) {
            rawCandidates.push("Bausubstanz/Energie:\n" + section.join("\n"));
        }

        const relevantLines = lines.filter((line) => /energie|heizung|energieträger|hauptenergieträger|baujahr/i.test(line));
        if (relevantLines.length) {
            rawCandidates.push("Weitere Treffer:\n" + relevantLines.slice(0, 30).join("\n"));
        }

        const rawText = clean(rawCandidates.join("\n\n"));

        return {
            energy_class: energyClass,
            energy_value_kwh: certificateStatus === "not_required" ? null : energyValue,
            energy_certificate_type: certificateStatus === "not_required" ? "unknown" : certificateType,
            energy_certificate_status: certificateStatus,
            heating_type: heatingType,
            energy_source: energySource,
            energy_construction_year: constructionYear,
            energy_data_source: "browser_userscript",
            energy_raw_text: rawText ? rawText.slice(0, 5000) : null,
        };
    }

    function hasUsefulData(data) {
        return Boolean(data.energy_class || data.energy_value_kwh !== null || data.energy_certificate_type !== "unknown" || data.energy_certificate_status !== "unknown" || data.heating_type || data.energy_source || data.energy_construction_year);
    }

    function certificateTypeLabel(value) {
        return {demand: "Bedarfsausweis", consumption: "Verbrauchsausweis", unknown: "—"}[value] || value;
    }

    function certificateStatusLabel(value) {
        return {available: "liegt vor", not_required: "nicht erforderlich", not_available_yet: "noch nicht verfügbar", unknown: "unbekannt"}[value] || value;
    }

    function removeModal() {
        document.getElementById("immo-energy-modal-backdrop")?.remove();
    }

    function showPreview(info, data) {
        removeModal();
        const backdrop = document.createElement("div");
        backdrop.id = "immo-energy-modal-backdrop";
        Object.assign(backdrop.style, {position: "fixed", inset: "0", background: "rgba(0,0,0,.55)", zIndex: "2147483646", display: "flex", alignItems: "center", justifyContent: "center", padding: "20px", fontFamily: "Arial, sans-serif"});
        const box = document.createElement("div");
        Object.assign(box.style, {background: "white", color: "#111", borderRadius: "12px", width: "min(620px, 96vw)", maxHeight: "90vh", overflow: "auto", padding: "20px", boxShadow: "0 12px 48px rgba(0,0,0,.35)"});
        const title = document.createElement("h2");
        title.textContent = "⚡ Energiedaten gefunden";
        title.style.margin = "0 0 14px";
        box.appendChild(title);
        const rows = [
            ["Portal", info.portal], ["ID", info.portalId], ["Status", certificateStatusLabel(data.energy_certificate_status)], ["Klasse", data.energy_class || "—"],
            ["Endenergie", data.energy_value_kwh !== null ? `${String(data.energy_value_kwh).replace(".", ",")} kWh/(m²·a)` : "—"],
            ["Ausweistyp", certificateTypeLabel(data.energy_certificate_type)], ["Heizung", data.heating_type || "—"], ["Energieträger", data.energy_source || "—"], ["Baujahr Energieausweis", data.energy_construction_year || "—"],
        ];
        const table = document.createElement("div");
        table.style.display = "grid";
        table.style.gridTemplateColumns = "180px 1fr";
        table.style.gap = "7px 12px";
        for (const [label, value] of rows) {
            const left = document.createElement("strong"); left.textContent = label;
            const right = document.createElement("div"); right.textContent = String(value);
            table.append(left, right);
        }
        box.appendChild(table);
        if (!hasUsefulData(data)) {
            const warning = document.createElement("p");
            warning.textContent = "⚠ Keine verwertbaren Energiedaten erkannt. Es wird nichts gesendet.";
            warning.style.fontWeight = "bold";
            warning.style.marginTop = "18px";
            box.appendChild(warning);
        }
        const actions = document.createElement("div");
        Object.assign(actions.style, {marginTop: "20px", display: "flex", gap: "10px", justifyContent: "flex-end", flexWrap: "wrap"});
        const cancel = document.createElement("button");
        cancel.textContent = "Abbrechen";
        Object.assign(cancel.style, {padding: "10px 14px", cursor: "pointer"});
        cancel.addEventListener("click", removeModal);
        const send = document.createElement("button");
        send.textContent = "⚡ An Monitor senden";
        send.disabled = !hasUsefulData(data);
        Object.assign(send.style, {padding: "10px 14px", cursor: send.disabled ? "not-allowed" : "pointer", fontWeight: "bold"});
        send.addEventListener("click", async () => {
            send.disabled = true; send.textContent = "Sende …";
            try {
                const result = await sendToMonitor(info, data);
                send.textContent = "✅ Gespeichert";
                const success = document.createElement("p");
                success.textContent = result.summary ? `✅ ${result.summary}` : "✅ Energiedaten gespeichert.";
                success.style.fontWeight = "bold";
                box.appendChild(success);
                window.setTimeout(removeModal, 1800);
            } catch (error) {
                send.disabled = false; send.textContent = "⚡ Erneut senden";
                const message = document.createElement("p");
                message.textContent = `❌ ${error.message}`;
                message.style.fontWeight = "bold";
                box.appendChild(message);
            }
        });
        actions.append(cancel, send); box.appendChild(actions); backdrop.appendChild(box); document.body.appendChild(backdrop);
        backdrop.addEventListener("click", (event) => { if (event.target === backdrop) removeModal(); });
    }

    function getToken() {
        let token = clean(GM_getValue(TOKEN_KEY, ""));
        if (!token) {
            token = clean(window.prompt("ENERGY_API_TOKEN eingeben. Er wird nur im Userscript-Speicher dieses Browsers abgelegt:"));
            if (token) GM_setValue(TOKEN_KEY, token);
        }
        return token;
    }

    function resetToken() {
        const current = clean(GM_getValue(TOKEN_KEY, ""));
        const token = clean(window.prompt("Neuen ENERGY_API_TOKEN eingeben:", current ? "" : ""));
        if (token) { GM_setValue(TOKEN_KEY, token); window.alert("API-Token gespeichert."); }
    }

    function sendToMonitor(info, data) {
        const token = getToken();
        if (!token) return Promise.reject(new Error("Kein API-Token gesetzt."));
        return new Promise((resolve, reject) => {
            GM_xmlhttpRequest({
                method: "POST", url: API_URL,
                headers: {Authorization: `Bearer ${token}`, "Content-Type": "application/json"},
                data: JSON.stringify({portal: info.portal, portal_id: info.portalId, energy: data}), timeout: 20000,
                onload(response) {
                    let body = null;
                    try { body = JSON.parse(response.responseText || "{}"); } catch (_error) { body = null; }
                    if (response.status >= 200 && response.status < 300 && body?.ok) { resolve(body); return; }
                    if (response.status === 401) {
                        GM_setValue(TOKEN_KEY, "");
                        reject(new Error("API-Token abgelehnt. Token wurde aus dem Userscript-Speicher gelöscht; beim nächsten Versuch neu eingeben."));
                        return;
                    }
                    reject(new Error(body?.error || `HTTP ${response.status}`));
                },
                onerror() { reject(new Error("Verbindung zur Energie-API fehlgeschlagen.")); },
                ontimeout() { reject(new Error("Zeitüberschreitung beim Senden.")); },
            });
        });
    }

    function getBrowserToken() {
        let token = clean(GM_getValue(BROWSER_TOKEN_KEY, ""));
        if (!token) {
            token = clean(window.prompt("BROWSER_ENRICH_TOKEN eingeben. Er wird nur im Userscript-Speicher dieses Browsers abgelegt:"));
            if (token) GM_setValue(BROWSER_TOKEN_KEY, token);
        }
        return token;
    }

    function resetBrowserToken() {
        const token = clean(window.prompt("Neuen BROWSER_ENRICH_TOKEN eingeben:"));
        if (token) { GM_setValue(BROWSER_TOKEN_KEY, token); window.alert("Browser-Enrichment-Token gespeichert."); }
    }

    function resetTokenMenu() {
        const choice = clean(window.prompt("Welchen Token ändern?\nE = Energie-API\nB = Browser-Enrichment", "E"));
        if (!choice) return;
        if (choice.toLowerCase() === "b") { resetBrowserToken(); return; }
        resetToken();
    }

    function getJsonLd() {
        return [...document.querySelectorAll('script[type="application/ld+json"]')].map((element) => element.textContent || "").filter(Boolean);
    }

    function pageLooksLikeCaptcha(text) {
        const value = String(text || "").toLowerCase();
        return value.includes("captcha") || value.includes("verify you are human") || value.includes("verify that you are human") || value.includes("security check") || value.includes("sicherheitsüberprüfung") || value.includes("ich bin kein roboter");
    }

    function getBrowserStatusElement() {
        let status = document.getElementById("immo-monitor-browser-status");
        if (status) return status;
        createPanel();
        return document.getElementById("immo-monitor-browser-status");
    }

    function showBrowserStatus(text, kind = "normal") {
        const status = getBrowserStatusElement();
        if (!status) return;
        status.textContent = text;
        const backgrounds = {normal: "#ffffff", working: "#fff7d6", success: "#e8f7e8", warning: "#fff1d6", error: "#fde7e7", blacklist: "#fde7e7"};
        status.style.background = backgrounds[kind] || backgrounds.normal;
    }

    function browserPayload(info, pageText) {
        return {portal: info.portal, portal_id: info.portalId, url: location.href, document_title: document.title || "", heading: document.querySelector("h1")?.innerText || "", page_text: pageText, energy_class_dom: extractEnergyClassFromDom(), json_ld: getJsonLd(), browser_timestamp: new Date().toISOString()};
    }

    function finishBrowserEnrichment() {
        browserFinished = true;
        if (browserCheckInterval) { window.clearInterval(browserCheckInterval); browserCheckInterval = null; }
    }

    function scheduleBrowserRetry(payload, reason) {
        if (!payloadMatchesCurrentObject(payload)) return;
        browserSending = false;
        if (browserAttempts >= BROWSER_MAX_ATTEMPTS) {
            finishBrowserEnrichment();
            showBrowserStatus("❌ Monitor: abgebrochen nach " + BROWSER_MAX_ATTEMPTS + " Versuchen (" + reason + ")", "error");
            return;
        }
        showBrowserStatus("⚠ Monitor: " + reason + " – neuer Versuch " + (browserAttempts + 1) + "/" + BROWSER_MAX_ATTEMPTS, "warning");
        window.setTimeout(() => sendBrowserEnrichment(payload), 2000);
    }

    function sendBrowserEnrichment(payload) {
        if (browserFinished || browserSending) return;
        if (!payloadMatchesCurrentObject(payload)) return;
        const token = getBrowserToken();
        if (!token) { finishBrowserEnrichment(); showBrowserStatus("⚠ Monitor: Browser-Token fehlt", "warning"); return; }
        browserAttempts += 1; browserSending = true;
        showBrowserStatus("🏠 Monitor: übertrage … (" + browserAttempts + "/" + BROWSER_MAX_ATTEMPTS + ")", "working");
        GM_xmlhttpRequest({
            method: "POST", url: BROWSER_API_URL,
            headers: {"Content-Type": "application/json", "X-Browser-Enrich-Token": token},
            data: JSON.stringify(payload), timeout: 15000,
            onload(response) {
                if (!payloadMatchesCurrentObject(payload)) return;
                browserSending = false;
                let result = {};
                try { result = JSON.parse(response.responseText || "{}"); } catch (_error) { result = {}; }
                if (response.status >= 200 && response.status < 300 && result.ok) {
                    finishBrowserEnrichment();
                    if (result.blacklisted) {
                        const terms = Array.isArray(result.blacklist_terms) ? result.blacklist_terms : [];
                        showBrowserStatus("🚫 BLACKLIST" + (terms.length ? ": " + terms.join(", ") : ""), "blacklist");
                        return;
                    }
                    if (result.database_status === "not_found") { showBrowserStatus("🆕 Noch nicht im Monitor", "warning"); return; }
                    if (result.duplicate) {
                        const dbId = result.property_id ? " · DB #" + result.property_id : "";
                        showBrowserStatus("♻️ Bereits im Monitor" + dbId, "success");
                        return;
                    }
                    showBrowserStatus("✅ Monitor: Browserdaten übernommen", "success");
                    return;
                }
                if (response.status === 403) {
                    GM_setValue(BROWSER_TOKEN_KEY, ""); finishBrowserEnrichment(); showBrowserStatus("❌ Monitor: Browser-Token abgelehnt", "error"); return;
                }
                scheduleBrowserRetry(payload, "HTTP " + response.status);
            },
            onerror() { scheduleBrowserRetry(payload, "nicht erreichbar"); },
            ontimeout() { scheduleBrowserRetry(payload, "Timeout"); },
        });
    }

    async function checkBrowserEnrichment() {
        if (browserFinished || browserSending) return;
        const info = portalInfo();
        if (!info) return;
        if (browserRouteChangedAt && Date.now() - browserRouteChangedAt < 1200) return;
        await prepareBrowserForEnrichment(info);
        if (browserFinished || browserSending) return;
        const currentInfo = portalInfo();
        if (!currentInfo || portalKey(currentInfo) !== portalKey(info)) return;
        const pageText = document.body?.innerText || document.body?.textContent || "";
        if (pageLooksLikeCaptcha(pageText)) { showBrowserStatus("🧩 Monitor: CAPTCHA – nach Freigabe wird erneut geprüft", "warning"); return; }
        if (pageText.length < 500) { showBrowserStatus("⏳ Monitor: Seite lädt …", "working"); return; }
        if (browserCheckInterval) { window.clearInterval(browserCheckInterval); browserCheckInterval = null; }
        const payload = browserPayload(info, pageText);
        closeAutoOpenedEnergyDetails();
        sendBrowserEnrichment(payload);
    }

    function positionPanel(panel, info) {
        const mobileImmowelt = info.portal === "immowelt" && window.matchMedia("(max-width: 768px)").matches;
        panel.style.right = mobileImmowelt ? "12px" : "18px";
        panel.style.bottom = mobileImmowelt ? "calc(96px + env(safe-area-inset-bottom, 0px))" : "18px";
        panel.style.maxWidth = mobileImmowelt ? "calc(100vw - 24px)" : "440px";
    }

    function createPanel() {
        if (document.getElementById("immo-monitor-panel")) return;
        const info = portalInfo();
        if (!info) return;
        const panel = document.createElement("div");
        panel.id = "immo-monitor-panel";
        Object.assign(panel.style, {position: "fixed", zIndex: "2147483645", display: "flex", flexDirection: "column", alignItems: "stretch", gap: "6px", fontFamily: "Arial, sans-serif"});
        const updatePanelPosition = () => positionPanel(panel, info);
        updatePanelPosition();
        window.addEventListener("resize", updatePanelPosition);
        const status = document.createElement("div");
        status.id = "immo-monitor-browser-status";
        status.textContent = "🏠 Monitor: prüfe Seite …";
        Object.assign(status.style, {borderRadius: "9px", padding: "9px 12px", background: "#ffffff", color: "#111", boxShadow: "0 3px 12px rgba(0,0,0,.25)", fontSize: "13px", fontWeight: "bold", lineHeight: "1.3"});
        const actions = document.createElement("div");
        Object.assign(actions.style, {display: "flex", justifyContent: "flex-end", gap: "6px"});
        const main = document.createElement("button");
        main.textContent = "⚡ Energie-Fallback";
        Object.assign(main.style, {border: "0", borderRadius: "9px", padding: "11px 14px", boxShadow: "0 3px 12px rgba(0,0,0,.25)", cursor: "pointer", fontWeight: "bold"});
        main.addEventListener("click", async () => {
            const currentInfo = portalInfo();
            if (!currentInfo) { window.alert("Exposé-ID konnte nicht erkannt werden."); return; }
            main.disabled = true; main.textContent = "⚡ Energiedaten lesen …";
            try { await prepareImmoweltEnergyDetails(); const data = extractEnergyData(); showPreview(currentInfo, data); }
            finally { main.disabled = false; main.textContent = "⚡ Energie-Fallback"; }
        });
        const settings = document.createElement("button");
        settings.textContent = "⚙"; settings.title = "API-Tokens ändern";
        Object.assign(settings.style, {border: "0", borderRadius: "9px", padding: "11px 12px", boxShadow: "0 3px 12px rgba(0,0,0,.25)", cursor: "pointer", fontWeight: "bold"});
        settings.addEventListener("click", resetTokenMenu);
        actions.append(main, settings); panel.append(status, actions); document.body.appendChild(panel);
    }

    const initialInfo = portalInfo();
    browserObjectKey = portalKey(initialInfo);
    window.setTimeout(createPanel, 1200);
    startBrowserCheckCycle(1500);
    browserRouteInterval = window.setInterval(checkPortalNavigation, 750);
})();
