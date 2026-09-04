"""Parse decimal degrees or two hemisphere-labelled DMS components."""
import re


DMS_COMPONENT = re.compile(
    r'(\d{1,3})\s*[°º]\s*(\d{1,2})\s*[\x27′’]\s*'
    r'(\d{1,2}(?:[.,]\d+)?)\s*[\x22″”]\s*([NSEW])',
    re.IGNORECASE,
)


def parse_coordinates(value):
    text = str(value or '').strip()
    matches = list(DMS_COMPONENT.finditer(text))
    if matches:
        if len(matches) != 2 or DMS_COMPONENT.sub('', text).strip(' ,;\t\n'):
            return None
        axes = {}
        for match in matches:
            degrees, minutes = int(match[1]), int(match[2])
            seconds, hemisphere = float(match[3].replace(',', '.')), match[4].upper()
            axis = 'lat' if hemisphere in 'NS' else 'lon'
            if axis in axes or minutes >= 60 or seconds >= 60:
                return None
            number = degrees + minutes / 60 + seconds / 3600
            axes[axis] = -number if hemisphere in 'SW' else number
        if set(axes) != {'lat', 'lon'}:
            return None
        latitude, longitude = axes['lat'], axes['lon']
    else:
        if re.search(r'[°º′″NSEW]', text, re.IGNORECASE):
            return None
        numbers = re.findall(r'[-+]?\d+(?:[.,]\d+)?', text)
        if len(numbers) != 2:
            return None
        latitude, longitude = (float(n.replace(',', '.')) for n in numbers)
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return None
    return latitude, longitude
