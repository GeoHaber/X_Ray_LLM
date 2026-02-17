"""
Semantic duplicate fixture — file B.
Same PURPOSE as dup_semantic_a.py functions but STRUCTURALLY DIFFERENT code.
Should be detected by Stage 3 ONLY (semantic similarity).

Calibration requirements:
  - code_similarity < 0.80  (different AST structure → Stage 2 misses)
  - semantic_similarity >= 0.50  (shared names/calls/docs → Stage 3 catches)

Strategy vs file A:
  - read_config:  open + json.load + manual close        (A uses with + json.load + for-loop)
  - deliver_notification:  smtplib + sendmail + list/join (A uses MIMEText + try/except)
  - clean_text:  str.translate + for-loop accumulation    (A uses re.sub + list comprehension)
  - calculate_file_hash:  pathlib.read_bytes + if/elif    (A uses while-loop + break)
"""
import json
import os
import hashlib
from pathlib import Path


def read_config(config_path: str, fallback: dict) -> dict:
    """Read configuration settings from a config file."""
    # B uses: open + json.load + manual close, if/else, dict-unpack (no with, no for)
    if not os.path.isfile(config_path):
        return dict(fallback)
    fh = open(config_path, "r", encoding="utf-8")
    parsed = json.load(fh)
    fh.close()
    merged = {**fallback, **parsed}
    return merged


def deliver_notification(target: str, title: str, content: str,
                         urgency: int = 0) -> bool:
    """Deliver a notification message to the target via email."""
    # B uses: smtplib + sendmail + list/join (no MIMEText, no try/except)
    import smtplib
    headers = [
        "From: system@app.com",
        f"To: {target}",
        f"Subject: {title}",
        f"X-Priority: {str(urgency)}",
        "",
        content,
    ]
    raw_message = "\r\n".join(headers)
    connection = smtplib.SMTP("mail.local", 25)
    connection.sendmail("system@app.com", [target], raw_message)
    connection.quit()
    return True


def clean_text(raw: str, strip_punctuation: bool = False) -> str:
    """Clean and normalize raw text for matching or indexing."""
    # B uses: str.translate, str.maketrans, for-loop accumulation, no regex
    import string
    output = raw.casefold().strip()
    lines = output.splitlines()
    parts = []
    for line in lines:
        parts.append(line.strip())
    output = " ".join(parts)
    while "  " in output:
        output = output.replace("  ", " ")
    if strip_punctuation:
        table = str.maketrans("", "", string.punctuation)
        output = output.translate(table)
    tokens = output.split()
    filtered = []
    for tok in tokens:
        if len(tok) > 1:
            filtered.append(tok)
    return " ".join(filtered)


def calculate_file_hash(file_path: str, hash_type: str = "sha256") -> str:
    """Calculate hash digest of a file from disk."""
    # B uses: pathlib, read_bytes, no loop, direct constructor
    data = Path(file_path).read_bytes()
    if hash_type == "sha256":
        h = hashlib.sha256(data)
    elif hash_type == "md5":
        h = hashlib.md5(data, usedforsecurity=False)
    elif hash_type == "sha1":
        h = hashlib.sha1(data, usedforsecurity=False)
    else:
        h = hashlib.new(hash_type, data)
    return h.hexdigest()
