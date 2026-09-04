"""Spatial municipality lookup followed by verification in the official directory."""
import json
import re
import urllib.parse
import urllib.request


OFFICIAL_DIRECTORY = 'https://www.statistikportal.de/de/gemeindeverzeichnis/{key}'
OVERPASS_URL = 'https://overpass-api.de/api/interpreter'


def _coordinates(property_data):
    latitude = property_data.get('manual_latitude') or property_data.get('latitude')
    longitude = property_data.get('manual_longitude') or property_data.get('longitude')
    if latitude is None or longitude is None:
        raise ValueError('Für das Objekt fehlen Koordinaten. Bitte zuerst die Lage präzisieren.')
    return float(latitude), float(longitude)


def _read(request, timeout=30):
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def lookup_municipality(property_data, read=_read):
    latitude, longitude = _coordinates(property_data)
    query = ('[out:json][timeout:20];'
             f'is_in({latitude:.7f},{longitude:.7f})->.a;'
             'rel(pivot.a)["boundary"="administrative"]["admin_level"="8"];out tags;')
    request = urllib.request.Request(
        OVERPASS_URL,
        data=urllib.parse.urlencode({'data': query}).encode(),
        headers={'User-Agent': 'immobilien-monitor/1.0 (municipality boundary lookup)'},
    )
    data = json.loads(read(request).decode('utf-8'))
    matches = []
    for element in data.get('elements', []):
        tags = element.get('tags', {})
        key = tags.get('de:amtlicher_gemeindeschluessel')
        name = tags.get('name:de') or tags.get('name')
        if re.fullmatch(r'\d{8}', str(key or '')) and name:
            matches.append((key, name.strip()))
    matches = list(dict.fromkeys(matches))
    if len(matches) != 1:
        raise ValueError('Die zuständige Gemeinde konnte räumlich nicht eindeutig bestimmt werden.')
    key, name = matches[0]
    source_url = OFFICIAL_DIRECTORY.format(key=key)
    official = read(urllib.request.Request(source_url, headers={
        'User-Agent': 'immobilien-monitor/1.0 (official municipality verification)',
        'Accept': 'text/html',
    }), timeout=20).decode('utf-8', errors='replace')
    name_tokens = [token for token in re.findall(r'[a-zäöüß]{4,}', name.casefold()) if token not in {'stadt', 'gemeinde'}]
    if key not in official or (name_tokens and not any(token in official.casefold() for token in name_tokens)):
        raise ValueError('Der Gemeindeschlüssel konnte im amtlichen Verzeichnis nicht bestätigt werden.')
    return {'key': key, 'name': name, 'source_url': source_url}
