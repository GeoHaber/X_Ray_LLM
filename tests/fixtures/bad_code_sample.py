# Fixture: intentionally bad code for lint/security testing
import json         # used below
import subprocess   # used below (but dangerously)
import hashlib      # used below (but weak)

x = 1; y = 2       # multiple statements on one line (E701)  # noqa: E702

def good_function():
    """This function is fine."""
    data = json.dumps({"key": "value"})
    return data

def bare_except_function():
    """Has a bare except."""
    try:
        pass
    except:             # bare except (E722)  # noqa: E722
        pass

def unused_var_function():
    """Has unused variable."""
    return "hello"

def shell_true_danger():
    """Uses shell=True - Bandit B602."""
    subprocess.run("echo hello", shell=True)

def weak_hash():
    """Uses MD5 - Bandit B324."""
    h = hashlib.md5(b"data")  # nosec B324
    return h.hexdigest()

def no_timeout_request():
    """Would trigger B113 if requests were imported."""
    pass

f_no_placeholder = "this has no placeholder"  # F541
