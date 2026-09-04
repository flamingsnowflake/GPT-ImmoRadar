"""Safe retrieval and text extraction for operator-provided dog-tax sources."""
import hashlib
import ipaddress
import re
import socket
import urllib.request
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse

from pypdf import PdfReader


MAX_DOCUMENT_BYTES = 12 * 1024 * 1024


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        if data.strip():
            self.parts.append(data.strip())


def _validate_public_https(url):
    parsed = urlparse(str(url or '').strip())
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Bitte einen öffentlichen HTTPS-Link senden.')
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)}
    except socket.gaierror as exc:
        raise ValueError('Der Hostname der Quelle konnte nicht aufgelöst werden.') from exc
    if not addresses:
        raise ValueError('Der Hostname der Quelle konnte nicht aufgelöst werden.')
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            raise ValueError('Die Quelle muss öffentlich erreichbar sein.')
    return parsed.geturl()


class _PublicHttpsRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return super().redirect_request(req, fp, code, msg, headers, _validate_public_https(newurl))


def fetch_document(url):
    url = _validate_public_https(url)
    request = urllib.request.Request(url, headers={
        'User-Agent': 'immobilien-monitor/1.0 (operator supplied municipal ordinance)',
        'Accept': 'application/pdf,text/html;q=0.9,text/plain;q=0.8',
    })
    with urllib.request.build_opener(_PublicHttpsRedirect()).open(request, timeout=30) as response:
        length = response.headers.get('Content-Length')
        if length and int(length) > MAX_DOCUMENT_BYTES:
            raise ValueError('Das Dokument ist größer als 12 MB.')
        content = response.read(MAX_DOCUMENT_BYTES + 1)
        content_type = response.headers.get_content_type()
        final_url = _validate_public_https(response.geturl())
    if len(content) > MAX_DOCUMENT_BYTES:
        raise ValueError('Das Dokument ist größer als 12 MB.')
    return final_url, content, content_type


def extract_document_text(content, content_type='', filename=''):
    if len(content) > MAX_DOCUMENT_BYTES:
        raise ValueError('Das Dokument ist größer als 12 MB.')
    is_pdf = content.startswith(b'%PDF-') or content_type == 'application/pdf' or filename.lower().endswith('.pdf')
    if is_pdf:
        try:
            reader = PdfReader(BytesIO(content))
            pages = [(page.extract_text() or '').strip() for page in reader.pages]
        except Exception as exc:
            raise ValueError('Die PDF konnte nicht gelesen werden.') from exc
        text = '\n\n'.join(f'[[SEITE {number}]]\n{page}' for number, page in enumerate(pages, 1) if page)
        if len(re.sub(r'\s+', '', text)) < 80:
            raise ValueError('Die PDF enthält kaum lesbaren Text. Sie ist vermutlich ein Scan; bitte eine Lesefassung oder Textquelle senden.')
        return text
    try:
        decoded = content.decode('utf-8')
    except UnicodeDecodeError:
        decoded = content.decode('latin-1', errors='replace')
    if 'html' in content_type or re.search(r'<(?:html|body|p)\b', decoded, re.I):
        parser = _TextExtractor()
        parser.feed(decoded)
        decoded = '\n'.join(parser.parts)
    if len(re.sub(r'\s+', '', decoded)) < 80:
        raise ValueError('Die Quelle enthält zu wenig lesbaren Text.')
    return decoded


def telegram_upload_reference(content, filename):
    safe_name = re.sub(r'[^A-Za-z0-9._-]+', '_', Path(filename or 'dokument.pdf').name)[:80]
    return f'telegram-upload:sha256:{hashlib.sha256(content).hexdigest()}:{safe_name}'
