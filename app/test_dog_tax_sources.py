import socket
import unittest
from unittest.mock import patch

from dog_tax_sources import _validate_public_https, extract_document_text, telegram_upload_reference


class DogTaxSourcesTest(unittest.TestCase):
    def test_private_network_sources_are_rejected(self):
        answer = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1', 443))]
        with patch('dog_tax_sources.socket.getaddrinfo', return_value=answer):
            with self.assertRaisesRegex(ValueError, 'öffentlich'):
                _validate_public_https('https://localhost/internal.pdf')

    def test_html_text_and_upload_reference_are_safe(self):
        html = ('<html><body><h1>Hundesteuersatzung</h1><p>'
                + 'Steuersatz und amtliche Erläuterung. ' * 10
                + '</p></body></html>').encode()
        text = extract_document_text(html, 'text/html', 'satzung.html')
        self.assertIn('Hundesteuersatzung', text)
        reference = telegram_upload_reference(b'synthetic PDF', '../../ Satzung 2026.pdf')
        self.assertRegex(reference, r'^telegram-upload:sha256:[0-9a-f]{64}:_Satzung_2026\.pdf$')


if __name__ == '__main__':
    unittest.main()
