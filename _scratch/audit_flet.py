"""AST-based audit of x_ray_flet.py for Flet API anti-patterns."""
import ast

with open("x_ray_flet.py", "r", encoding="utf-8") as f:
    src = f.read()

tree = ast.parse(src)
issues = []

for node in ast.walk(tree):
    if not isinstance(node, ast.Call):
        continue

    # 1. Padding/Margin.symmetric with positional args
    if isinstance(node.func, ast.Attribute) and node.func.attr == "symmetric":
        if isinstance(node.func.value, ast.Attribute):
            cls = node.func.value.attr
            if cls in ("Padding", "Margin") and node.args:
                issues.append(f"L{node.lineno}: {cls}.symmetric() with positional args")

    # 2. ft.Tabs() given tabs= keyword (invalid)
    if isinstance(node.func, ast.Attribute) and node.func.attr == "Tabs":
        for kw in node.keywords:
            if kw.arg == "tabs":
                issues.append(f"L{node.lineno}: ft.Tabs() given tabs= keyword (invalid)")

    # 3. ft.Border() with 1 positional arg
    if isinstance(node.func, ast.Attribute) and node.func.attr == "Border":
        if isinstance(node.func.value, ast.Name) and node.func.value.id == "ft":
            if len(node.args) == 1:
                issues.append(f"L{node.lineno}: ft.Border() with 1 positional arg")

    # 4. scroll as string instead of enum
    for kw in node.keywords:
        if kw.arg == "scroll" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
            issues.append(f'L{node.lineno}: scroll="{kw.value.value}" should use ft.ScrollMode.X')

    # 5. alignment as string
    for kw in node.keywords:
        if kw.arg == "alignment" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
            issues.append(f'L{node.lineno}: alignment="{kw.value.value}" should use ft.alignment.X')

    # 6. theme_mode as string
    for kw in node.keywords:
        if kw.arg == "theme_mode" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
            issues.append(f'L{node.lineno}: theme_mode="{kw.value.value}" should use ft.ThemeMode.X')

if issues:
    print(f"Found {len(issues)} potential issues:")
    for i in issues:
        print(f"  {i}")
else:
    print("No issues found - all Flet API calls look correct!")
