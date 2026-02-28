"""Analyze the X_Ray scan report and prepare fix targets."""
import json
import os
import collections

REPORT = os.path.join(os.path.dirname(__file__), '..', 'zen_baseline_clean.json')
ZEN = r'C:\Users\Yo930\Desktop\_Python\Projects\ZEN_AI_RAG'


def load_report():
    for enc in ('utf-8-sig', 'utf-16', 'utf-8', 'latin-1'):
        try:
            with open(REPORT, 'r', encoding=enc) as f:
                return json.load(f)
        except Exception:
            continue
    # Try from ZEN dir
    alt = os.path.join(ZEN, 'zen_baseline_clean.json')
    for enc in ('utf-8-sig', 'utf-16', 'utf-8', 'latin-1'):
        try:
            with open(alt, 'r', encoding=enc) as f:
                return json.load(f)
        except Exception:
            continue
    raise RuntimeError("Cannot load report")


def main():
    d = load_report()
    
    # Security
    sec = d.get('security', {}).get('issues', [])
    print(f"=== SECURITY ({len(sec)} total) ===")
    for sev in ['CRITICAL', 'WARNING', 'INFO']:
        items = [i for i in sec if i.get('severity') == sev]
        print(f"  {sev}: {len(items)}")
        if sev in ('CRITICAL', 'WARNING'):
            for it in items:
                fp = it.get('file_path', '')
                ln = it.get('line', '')
                rc = it.get('rule_code', '')
                msg = it.get('message', '')[:90]
                print(f"    {fp}:{ln} [{rc}] {msg}")
    
    # Lint
    lint = d.get('lint', {}).get('issues', [])
    print(f"\n=== LINT ({len(lint)} total) ===")
    by_code = collections.Counter(i.get('rule_code', '') for i in lint)
    for code, cnt in by_code.most_common():
        sev = 'CRIT' if any(i.get('severity') == 'CRITICAL' and i.get('rule_code') == code for i in lint) else \
              'WARN' if any(i.get('severity') == 'WARNING' and i.get('rule_code') == code for i in lint) else 'INFO'
        print(f"  {cnt:4d} {code:6s} ({sev})")
    
    # Smells
    smells = d.get('smells', {}).get('issues', [])
    print(f"\n=== SMELLS ({len(smells)} total) ===")
    for sev in ['CRITICAL', 'WARNING', 'INFO']:
        items = [i for i in smells if i.get('severity') == sev]
        cats = collections.Counter(i.get('category', '') for i in items)
        print(f"  {sev}: {len(items)}")
        for cat, cnt in cats.most_common():
            print(f"    {cnt:3d} {cat}")

    # Critical smells - show top files
    crit_smells = [i for i in smells if i.get('severity') == 'CRITICAL']
    files_crit = collections.Counter(i.get('file_path', '') for i in crit_smells)
    print(f"\n=== TOP FILES BY CRITICAL SMELLS ===")
    for fp, cnt in files_crit.most_common(20):
        print(f"  {cnt:3d} {fp}")

    # Duplicates   
    dups = d.get('duplicates', {})
    groups = dups.get('groups', [])
    print(f"\n=== DUPLICATES ({len(groups)} groups) ===")
    # Show size distribution
    sizes = [g.get('lines', g.get('line_count', 0)) for g in groups]
    if sizes:
        print(f"  Line counts: min={min(sizes)}, max={max(sizes)}, avg={sum(sizes)/len(sizes):.1f}")


if __name__ == '__main__':
    main()
