"""
Semantic duplicate fixture — file A.
Contains functions that do the same THING as those in dup_semantic_b.py
but with STRUCTURALLY DIFFERENT code (different AST node types).

Calibration requirements:
  - code_similarity < 0.80  (different AST structure → Stage 2 misses)
  - semantic_similarity >= 0.50  (shared names/calls/docs → Stage 3 catches)

Strategy: use with-statement where B uses pathlib, try/except where B uses
if-checks, re.sub where B uses str.translate, while-loop where B uses
if/elif chain.
"""
import json
import hashlib


def load_config(filepath: str, defaults: dict) -> dict:
    """Load configuration settings from a file on disk."""
    # A uses: with-statement, json.load, for-loop merge
    result = dict(defaults)
    with open(filepath, "r", encoding="utf-8") as fh:
        data = json.load(fh)
        for key in data:
            result[key] = data[key]
    return result


def send_notification(recipient: str, subject: str, body: str,
                      priority: int = 0) -> bool:
    """Send a notification message to a recipient via email."""
    # A uses: smtplib + MIMEText, try/except, SMTP.send_message
    import smtplib
    from email.mime.text import MIMEText
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = "noreply@app.com"
    msg["To"] = recipient
    msg["X-Priority"] = str(priority)
    try:
        server = smtplib.SMTP("localhost", 587)
        server.send_message(msg)
        server.quit()
        return True
    except smtplib.SMTPException:
        return False


def normalize_text(text: str, keep_punctuation: bool = False) -> str:
    """Normalize and clean text for comparison or indexing."""
    # A uses: re.sub (regex-based), list comprehension, str.join
    import re
    text = text.lower().strip()
    text = re.sub(r"\s+", " ", text)
    if not keep_punctuation:
        text = re.sub(r"[^\w\s]", "", text)
    words = text.split()
    return " ".join(w for w in words if len(w) > 1)


def compute_file_hash(filepath: str, algorithm: str = "sha256") -> str:
    """Compute hash digest of a file on disk."""
    # A uses: while-loop with break, hashlib.new, chunked read
    hasher = hashlib.new(algorithm)
    with open(filepath, "rb") as fh:
        while True:
            chunk = fh.read(8192)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()
