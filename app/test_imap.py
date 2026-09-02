import os
import imaplib
import email
from email.header import decode_header

host = os.environ["IMAP_HOST"]
port = int(os.environ["IMAP_PORT"])
user = os.environ["IMAP_USER"]
password = os.environ["IMAP_PASSWORD"]
mailbox = os.environ.get("IMAP_MAILBOX", "INBOX")

print(f"Connecting to {host}:{port} ...")

imap = imaplib.IMAP4_SSL(host, port)

print("TLS connection established.")

imap.login(user, password)
print("IMAP authentication successful.")

imap.select(mailbox)

status, data = imap.search(None, "ALL")

if status != "OK":
    raise RuntimeError("Could not search mailbox")

message_ids = data[0].split()

print(f"Messages in mailbox: {len(message_ids)}")

for msg_id in message_ids[-5:]:
    status, msg_data = imap.fetch(msg_id, "(RFC822)")

    if status != "OK":
        continue

    msg = email.message_from_bytes(msg_data[0][1])

    subject = msg.get("Subject", "")
    decoded = decode_header(subject)

    subject_text = ""

    for part, encoding in decoded:
        if isinstance(part, bytes):
            subject_text += part.decode(encoding or "utf-8", errors="replace")
        else:
            subject_text += part

    print("-" * 60)
    print("ID:", msg_id.decode())
    print("From:", msg.get("From"))
    print("Date:", msg.get("Date"))
    print("Subject:", subject_text)

imap.logout()

print("Done.")
