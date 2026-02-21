"""
Tests for Tier-3 transpiler expansion:
  - time module handlers
  - datetime module handlers
  - subprocess module handlers
  - hashlib module handlers
  - argparse module handlers
  - collections module handlers
  - functools module handlers
  - itertools module handlers
  - logging module handlers
  - expanded sys handlers
  - async/await support
  - inline import handling
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from Analysis.transpiler import transpile_function_code
import traceback

PASS = 0
FAIL = 0

def check(label: str, code: str, must_contain: list[str], must_not_contain: list[str] = None):
    global PASS, FAIL
    must_not_contain = must_not_contain or []
    try:
        rust = transpile_function_code(code)
    except Exception as e:
        FAIL += 1
        print(f"  [FAIL] {label}: EXCEPTION {e}")
        traceback.print_exc()
        return

    ok = True
    for needle in must_contain:
        if needle not in rust:
            print(f"  [FAIL] {label}: missing '{needle}'")
            print(f"         Output: {rust[:300]}")
            ok = False
            break
    for needle in must_not_contain:
        if needle in rust:
            print(f"  [FAIL] {label}: should NOT contain '{needle}'")
            print(f"         Output: {rust[:300]}")
            ok = False
            break
    if ok:
        PASS += 1
        print(f"  [PASS] {label}")
    else:
        FAIL += 1


# ── time module ─────────────────────────────────────────────────────

print("\n=== time module ===")

check("time.time()",
      "def get_ts():\n    return time.time()",
      ["SystemTime", "UNIX_EPOCH", "as_secs_f64"])

check("time.sleep()",
      "def wait(n):\n    time.sleep(n)",
      ["std::thread::sleep", "Duration::from_secs_f64"])

check("time.perf_counter()",
      "def bench():\n    t = time.perf_counter()\n    return t",
      ["Instant", "as_secs_f64"])


# ── datetime module ─────────────────────────────────────────────────

print("\n=== datetime module ===")

check("datetime.now()",
      "def get_now():\n    return datetime.now()",
      ["chrono::Local::now()"])

check("datetime.utcnow()",
      "def get_utc():\n    return datetime.utcnow()",
      ["chrono::Utc::now()"])

check("datetime.strptime()",
      "def parse_date(s, fmt):\n    return datetime.strptime(s, fmt)",
      ["NaiveDateTime::parse_from_str"])

check("datetime.fromtimestamp()",
      "def from_ts(ts):\n    return datetime.fromtimestamp(ts)",
      ["from_timestamp"])


# ── subprocess module ───────────────────────────────────────────────

print("\n=== subprocess module ===")

check("subprocess.run()",
      "def run_cmd(cmd):\n    subprocess.run(cmd)",
      ["std::process::Command", "status()"])

check("subprocess.check_output()",
      "def get_output(cmd):\n    return subprocess.check_output(cmd)",
      ["Command::new", "output()", "stdout"])

check("subprocess.Popen()",
      "def start(cmd):\n    p = subprocess.Popen(cmd)\n    return p",
      ["Command::new", "spawn()"])


# ── hashlib module ──────────────────────────────────────────────────

print("\n=== hashlib module ===")

check("hashlib.sha256()",
      "def hash_it(data):\n    return hashlib.sha256(data)",
      ["Sha256::digest"])

check("hashlib.md5()",
      "def md5_hash(data):\n    return hashlib.md5(data)",
      ["Md5::digest"])


# ── collections module ──────────────────────────────────────────────

print("\n=== collections module ===")

check("collections.Counter()",
      "def count_items(items):\n    return collections.Counter(items)",
      ["fold", "HashMap", "or_insert"])

check("collections.deque()",
      "def make_queue():\n    return collections.deque()",
      ["VecDeque::new()"])

check("collections.defaultdict()",
      "def make_dd():\n    return collections.defaultdict()",
      ["HashMap::new()"])


# ── argparse module ─────────────────────────────────────────────────

print("\n=== argparse module ===")

check("argparse.ArgumentParser()",
      'def parse():\n    parser = argparse.ArgumentParser("test")\n    return parser',
      ["clap::Command::new"])


# ── functools module ────────────────────────────────────────────────

print("\n=== functools module ===")

check("functools.reduce()",
      "def total(items):\n    return functools.reduce(add, items)",
      ["fold"])


# ── itertools module ────────────────────────────────────────────────

print("\n=== itertools module ===")

check("itertools.chain()",
      "def merge(a, b):\n    return itertools.chain(a, b)",
      [".chain("])

check("itertools.product()",
      "def cartesian(a, b):\n    return itertools.product(a, b)",
      ["iproduct!"])

check("itertools.combinations()",
      "def combos(items, r):\n    return itertools.combinations(items, r)",
      [".combinations("])


# ── logging module ──────────────────────────────────────────────────

print("\n=== logging module ===")

check("logging.info()",
      'def log_it(msg):\n    logging.info(msg)',
      ["log::info!"])

check("logging.error()",
      'def log_err(msg):\n    logging.error(msg)',
      ["log::error!"])

check("logging.warning()",
      'def log_warn(msg):\n    logging.warning(msg)',
      ["log::warn!"])

check("logging.basicConfig()",
      'def setup_log():\n    logging.basicConfig()',
      ["env_logger::init"])


# ── expanded sys module ─────────────────────────────────────────────

print("\n=== expanded sys module ===")

check("sys.exit()",
      "def bail(code):\n    sys.exit(code)",
      ["std::process::exit"])

check("sys.argv as attribute",
      "def get_args():\n    return sys.argv",
      ["std::env::args()"])

check("sys.platform as attribute",
      "def get_plat():\n    return sys.platform",
      ["std::env::consts::OS"])

check("sys.getsizeof()",
      "def size_of(obj):\n    return sys.getsizeof(obj)",
      ["std::mem::size_of_val"])


# ── async/await ─────────────────────────────────────────────────────

print("\n=== async/await ===")

check("async function def",
      "async def fetch(url):\n    result = await get(url)\n    return result",
      ["async fn", ".await"],
      must_not_contain=["fn fn"])

check("async with await expression",
      "async def process(data):\n    x = await transform(data)\n    return x",
      ["async fn", ".await"])


# ── inline imports ──────────────────────────────────────────────────

print("\n=== inline imports ===")

check("inline import becomes comment",
      "def helper():\n    import os\n    return os.getcwd()",
      ["// import os", "current_dir"])

check("inline from-import becomes comment",
      "def helper2():\n    from pathlib import Path\n    return Path('.')",
      ["// from pathlib import Path"])


# ── module constants as attributes ──────────────────────────────────

print("\n=== module constants ===")

check("subprocess.PIPE",
      "def run_piped(cmd):\n    p = subprocess.PIPE\n    return p",
      ["Stdio::piped()"])

check("logging.DEBUG",
      "def get_level():\n    return logging.DEBUG",
      ["log::Level::Debug"])

check("sys.stdout",
      "def get_out():\n    return sys.stdout",
      ["std::io::stdout()"])


# ── Summary ─────────────────────────────────────────────────────────

print(f"\n{'='*50}")
print(f"  Tier-3 Results: {PASS} passed, {FAIL} failed out of {PASS+FAIL}")
print(f"{'='*50}")
if FAIL == 0:
    print("  ALL TESTS PASSED!")
else:
    print(f"  {FAIL} FAILURES — review above")
    sys.exit(1)
