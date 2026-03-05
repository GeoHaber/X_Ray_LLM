"""
Core.i18n — Internationalization string tables for X-Ray UI
=============================================================

Usage::

    from Core.i18n import t, set_locale, LOCALES

    set_locale("ro")          # switch language
    label = t("scan_start")   # → "Începe Scanarea"

Add new languages by extending ``_STRINGS``.
"""

from __future__ import annotations

from typing import Dict

# ── Supported locales ────────────────────────────────────────────────────────

LOCALES: Dict[str, str] = {
    "en": "English",
    "ro": "Română",
    "es": "Español",
    "fr": "Français",
    "de": "Deutsch",
}

_current_locale: str = "en"

# ── String tables ────────────────────────────────────────────────────────────

_STRINGS: Dict[str, Dict[str, str]] = {
    # ── App chrome ───────────────────────────────────────────────────────
    "app_title": {
        "en": "X-Ray Code Scanner",
        "ro": "X-Ray Scanner de Cod",
        "es": "X-Ray Escáner de Código",
        "fr": "X-Ray Analyseur de Code",
        "de": "X-Ray Code-Analysator",
    },
    "app_subtitle": {
        "en": "Code Quality Analyzer",
        "ro": "Analizor Calitate Cod",
        "es": "Analizador de Calidad",
        "fr": "Analyseur de Qualité",
        "de": "Code-Qualitätsanalyse",
    },
    "quality_score": {
        "en": "Quality Score",
        "ro": "Scor Calitate",
        "es": "Puntuación de Calidad",
        "fr": "Score Qualité",
        "de": "Qualitätswert",
    },
    # ── Sidebar ──────────────────────────────────────────────────────────
    "project_scope": {
        "en": "Project Scope",
        "ro": "Domeniu Proiect",
        "es": "Alcance del Proyecto",
        "fr": "Portée du Projet",
        "de": "Projektumfang",
    },
    "select_directory": {
        "en": "Select Directory",
        "ro": "Selectează Director",
        "es": "Seleccionar Directorio",
        "fr": "Choisir un Répertoire",
        "de": "Verzeichnis wählen",
    },
    "no_dir_selected": {
        "en": "No directory selected",
        "ro": "Niciun director selectat",
        "es": "Ningún directorio",
        "fr": "Aucun répertoire",
        "de": "Kein Verzeichnis",
    },
    "scan_modes": {
        "en": "Scan Modes",
        "ro": "Moduri Scanare",
        "es": "Modos de Escaneo",
        "fr": "Modes d'Analyse",
        "de": "Scan-Modi",
    },
    "scan_start": {
        "en": "Start Full Scan",
        "ro": "Începe Scanarea",
        "es": "Iniciar Escaneo",
        "fr": "Lancer l'Analyse",
        "de": "Scan Starten",
    },
    "exclude_dirs": {
        "en": "Exclude Directories",
        "ro": "Excludere Directoare",
        "es": "Excluir Directorios",
        "fr": "Exclure Répertoires",
        "de": "Verzeichnisse ausschließen",
    },
    "presets": {
        "en": "Presets",
        "ro": "Presetări",
        "es": "Preajustes",
        "fr": "Préréglages",
        "de": "Voreinstellungen",
    },
    "preset_quick": {
        "en": "Quick",
        "ro": "Rapid",
        "es": "Rápido",
        "fr": "Rapide",
        "de": "Schnell",
    },
    "preset_full": {
        "en": "Full",
        "ro": "Complet",
        "es": "Completo",
        "fr": "Complet",
        "de": "Vollständig",
    },
    "preset_custom": {
        "en": "Custom",
        "ro": "Personalizat",
        "es": "Personalizado",
        "fr": "Personnalisé",
        "de": "Benutzerdefiniert",
    },
    # ── Analyzers ────────────────────────────────────────────────────────
    "smells": {
        "en": "Code Smells",
        "ro": "Mirosuri Cod",
        "es": "Olores de Código",
        "fr": "Odeurs de Code",
        "de": "Code-Gerüche",
    },
    "duplicates": {
        "en": "Duplicates",
        "ro": "Duplicate",
        "es": "Duplicados",
        "fr": "Doublons",
        "de": "Duplikate",
    },
    "lint": {
        "en": "Lint (Ruff)",
        "ro": "Lint (Ruff)",
        "es": "Lint (Ruff)",
        "fr": "Lint (Ruff)",
        "de": "Lint (Ruff)",
    },
    "security": {
        "en": "Security (Bandit)",
        "ro": "Securitate (Bandit)",
        "es": "Seguridad (Bandit)",
        "fr": "Sécurité (Bandit)",
        "de": "Sicherheit (Bandit)",
    },
    "rustify": {
        "en": "Rustify",
        "ro": "Rustificare",
        "es": "Rustificar",
        "fr": "Rustifier",
        "de": "Rustifizieren",
    },
    "ui_compat": {
        "en": "UI Compat",
        "ro": "Compat. UI",
        "es": "Compat. UI",
        "fr": "Compat. UI",
        "de": "UI-Kompatibilität",
    },
    # ── Tabs ─────────────────────────────────────────────────────────────
    "tab_smells": {
        "en": "Smells",
        "ro": "Mirosuri",
        "es": "Olores",
        "fr": "Odeurs",
        "de": "Gerüche",
    },
    "tab_duplicates": {
        "en": "Duplicates",
        "ro": "Duplicate",
        "es": "Duplicados",
        "fr": "Doublons",
        "de": "Duplikate",
    },
    "tab_lint": {"en": "Lint", "ro": "Lint", "es": "Lint", "fr": "Lint", "de": "Lint"},
    "tab_security": {
        "en": "Security",
        "ro": "Securitate",
        "es": "Seguridad",
        "fr": "Sécurité",
        "de": "Sicherheit",
    },
    "tab_rustify": {
        "en": "Rustify",
        "ro": "Rustificare",
        "es": "Rustificar",
        "fr": "Rustifier",
        "de": "Rustifizieren",
    },
    "tab_heatmap": {
        "en": "Heatmap",
        "ro": "Hartă Termică",
        "es": "Mapa de Calor",
        "fr": "Carte Thermique",
        "de": "Heatmap",
    },
    "tab_complexity": {
        "en": "Complexity",
        "ro": "Complexitate",
        "es": "Complejidad",
        "fr": "Complexité",
        "de": "Komplexität",
    },
    "tab_auto_rustify": {
        "en": "Auto-Rustify",
        "ro": "Auto-Rustificare",
        "es": "Auto-Rustificar",
        "fr": "Auto-Rustifier",
        "de": "Auto-Rustifizieren",
    },
    "tab_ui_compat": {
        "en": "UI Compat",
        "ro": "Compat. UI",
        "es": "Compat. UI",
        "fr": "Compat. UI",
        "de": "UI-Kompatibilität",
    },
    # ── Severity / Status ────────────────────────────────────────────────
    "critical": {
        "en": "Critical",
        "ro": "Critic",
        "es": "Crítico",
        "fr": "Critique",
        "de": "Kritisch",
    },
    "warning": {
        "en": "Warning",
        "ro": "Avertisment",
        "es": "Advertencia",
        "fr": "Avertissement",
        "de": "Warnung",
    },
    "info": {
        "en": "Info",
        "ro": "Informație",
        "es": "Información",
        "fr": "Information",
        "de": "Information",
    },
    "total": {
        "en": "Total",
        "ro": "Total",
        "es": "Total",
        "fr": "Total",
        "de": "Gesamt",
    },
    # ── Metrics ──────────────────────────────────────────────────────────
    "files": {
        "en": "Files",
        "ro": "Fișiere",
        "es": "Archivos",
        "fr": "Fichiers",
        "de": "Dateien",
    },
    "functions": {
        "en": "Functions",
        "ro": "Funcții",
        "es": "Funciones",
        "fr": "Fonctions",
        "de": "Funktionen",
    },
    "classes": {
        "en": "Classes",
        "ro": "Clase",
        "es": "Clases",
        "fr": "Classes",
        "de": "Klassen",
    },
    "duration": {
        "en": "Duration",
        "ro": "Durată",
        "es": "Duración",
        "fr": "Durée",
        "de": "Dauer",
    },
    "score": {
        "en": "Score",
        "ro": "Scor",
        "es": "Puntuación",
        "fr": "Score",
        "de": "Punkte",
    },
    "grade": {
        "en": "Grade",
        "ro": "Notă",
        "es": "Calificación",
        "fr": "Note",
        "de": "Note",
    },
    "pure": {"en": "Pure", "ro": "Pur", "es": "Puro", "fr": "Pur", "de": "Rein"},
    "impure": {
        "en": "Impure",
        "ro": "Impur",
        "es": "Impuro",
        "fr": "Impur",
        "de": "Unrein",
    },
    "exact": {
        "en": "Exact",
        "ro": "Exact",
        "es": "Exacto",
        "fr": "Exact",
        "de": "Exakt",
    },
    "near": {
        "en": "Near",
        "ro": "Aproape",
        "es": "Cercano",
        "fr": "Proche",
        "de": "Nahe",
    },
    "semantic": {
        "en": "Semantic",
        "ro": "Semantic",
        "es": "Semántico",
        "fr": "Sémantique",
        "de": "Semantisch",
    },
    "top_score": {
        "en": "Top Score",
        "ro": "Scor Maxim",
        "es": "Puntuación Máxima",
        "fr": "Meilleur Score",
        "de": "Höchstwertung",
    },
    "scored": {
        "en": "Scored",
        "ro": "Evaluat",
        "es": "Evaluado",
        "fr": "Évalué",
        "de": "Bewertet",
    },
    "auto_fixable": {
        "en": "Auto-fixable",
        "ro": "Reparabil automat",
        "es": "Auto-reparable",
        "fr": "Auto-réparable",
        "de": "Auto-behebbar",
    },
    "groups": {
        "en": "Groups",
        "ro": "Grupuri",
        "es": "Grupos",
        "fr": "Groupes",
        "de": "Gruppen",
    },
    "involved": {
        "en": "Functions Involved",
        "ro": "Funcții Implicate",
        "es": "Funciones Involucradas",
        "fr": "Fonctions Impliquées",
        "de": "Beteiligte Funktionen",
    },
    # ── Actions ──────────────────────────────────────────────────────────
    "auto_fix": {
        "en": "Auto-Fix All",
        "ro": "Repară Automat Tot",
        "es": "Reparar Todo Auto",
        "fr": "Tout Corriger Auto",
        "de": "Alles Auto-Reparieren",
    },
    "export_json": {
        "en": "Export JSON",
        "ro": "Exportă JSON",
        "es": "Exportar JSON",
        "fr": "Exporter JSON",
        "de": "JSON Exportieren",
    },
    "export_markdown": {
        "en": "Export Markdown",
        "ro": "Exportă Markdown",
        "es": "Exportar Markdown",
        "fr": "Exporter Markdown",
        "de": "Markdown Exportieren",
    },
    "run_pipeline": {
        "en": "Run Pipeline",
        "ro": "Rulează Pipeline",
        "es": "Ejecutar Pipeline",
        "fr": "Lancer Pipeline",
        "de": "Pipeline Starten",
    },
    # ── Messages ─────────────────────────────────────────────────────────
    "no_issues": {
        "en": "No issues found!",
        "ro": "Nicio problemă găsită!",
        "es": "¡Sin problemas!",
        "fr": "Aucun problème trouvé !",
        "de": "Keine Probleme gefunden!",
    },
    "scanning": {
        "en": "Scanning...",
        "ro": "Scanare...",
        "es": "Escaneando...",
        "fr": "Analyse en cours...",
        "de": "Wird gescannt...",
    },
    "scan_complete": {
        "en": "Scan complete",
        "ro": "Scanare completă",
        "es": "Escaneo completado",
        "fr": "Analyse terminée",
        "de": "Scan abgeschlossen",
    },
    "select_dir_first": {
        "en": "Please select a directory first!",
        "ro": "Selectează un director mai întâi!",
        "es": "¡Seleccione un directorio primero!",
        "fr": "Veuillez d'abord choisir un répertoire !",
        "de": "Bitte erst ein Verzeichnis wählen!",
    },
    "ready": {
        "en": "Ready for Analysis",
        "ro": "Pregătit pentru Analiză",
        "es": "Listo para Análisis",
        "fr": "Prêt pour l'Analyse",
        "de": "Bereit zur Analyse",
    },
    "ready_desc": {
        "en": "Select a directory and click 'Start Full Scan' to begin.",
        "ro": "Selectează un director și apasă 'Începe Scanarea'.",
        "es": "Seleccione un directorio y haga clic en 'Iniciar Escaneo'.",
        "fr": "Choisissez un répertoire et cliquez sur 'Lancer l'Analyse'.",
        "de": "Verzeichnis wählen und 'Scan Starten' klicken.",
    },
    # ── Onboarding ───────────────────────────────────────────────────────
    "onboard_title": {
        "en": "Welcome to X-Ray",
        "ro": "Bine ai venit la X-Ray",
        "es": "Bienvenido a X-Ray",
        "fr": "Bienvenue sur X-Ray",
        "de": "Willkommen bei X-Ray",
    },
    "onboard_step1_title": {
        "en": "Pick a Project Folder",
        "ro": "Alege un Director",
        "es": "Elija una Carpeta",
        "fr": "Choisissez un Dossier",
        "de": "Wählen Sie einen Ordner",
    },
    "onboard_step1_desc": {
        "en": "Use 'Select Directory' in the sidebar to point X-Ray at any Python project.",
        "ro": "Folosește 'Selectează Director' din bara laterală pentru a alege un proiect Python.",
        "es": "Use 'Seleccionar Directorio' en la barra lateral para apuntar a un proyecto Python.",
        "fr": "Utilisez 'Choisir un Répertoire' dans la barre latérale pour pointer vers un projet Python.",
        "de": "Verwenden Sie 'Verzeichnis wählen' in der Seitenleiste, um auf ein Python-Projekt zu zeigen.",
    },
    "onboard_step2_title": {
        "en": "Smells & Duplicates",
        "ro": "Mirosuri & Duplicate",
        "es": "Olores y Duplicados",
        "fr": "Odeurs & Doublons",
        "de": "Gerüche & Duplikate",
    },
    "onboard_step2_desc": {
        "en": "🔍 Smells — finds bad patterns (long functions, deep nesting, magic numbers).\n📋 Duplicates — detects copy-pasted code blocks across files.",
        "ro": "🔍 Mirosuri — găsește tipare proaste (funcții lungi, imbricare adâncă).\n📋 Duplicate — detectează blocuri de cod copiate între fișiere.",
        "es": "🔍 Olores — encuentra patrones malos (funciones largas, anidamiento profundo).\n📋 Duplicados — detecta bloques de código copiados entre archivos.",
        "fr": "🔍 Odeurs — trouve les mauvais patterns (fonctions longues, imbrication profonde).\n📋 Doublons — détecte les blocs de code copiés-collés.",
        "de": "🔍 Gerüche — findet schlechte Muster (lange Funktionen, tiefe Verschachtelung).\n📋 Duplikate — erkennt kopierte Codeblöcke.",
    },
    "onboard_step3_title": {
        "en": "Lint & Security",
        "ro": "Lint & Securitate",
        "es": "Lint y Seguridad",
        "fr": "Lint & Sécurité",
        "de": "Lint & Sicherheit",
    },
    "onboard_step3_desc": {
        "en": "⚡ Lint — runs Ruff for style errors, unused imports, and formatting issues.\n🛡️ Security — runs Bandit to flag potential vulnerabilities (SQL injection, hardcoded secrets, etc.).",
        "ro": "⚡ Lint — rulează Ruff pentru erori de stil și importuri nefolosite.\n🛡️ Securitate — rulează Bandit pentru vulnerabilități (injecție SQL, secrete hardcodate).",
        "es": "⚡ Lint — ejecuta Ruff para errores de estilo e imports sin usar.\n🛡️ Seguridad — ejecuta Bandit para detectar vulnerabilidades.",
        "fr": "⚡ Lint — lance Ruff pour les erreurs de style et imports inutilisés.\n🛡️ Sécurité — lance Bandit pour les vulnérabilités potentielles.",
        "de": "⚡ Lint — führt Ruff für Stilfehler und unbenutzte Imports aus.\n🛡️ Sicherheit — führt Bandit für potenzielle Schwachstellen aus.",
    },
    "onboard_step4_title": {
        "en": "Rustify",
        "ro": "Rustificare",
        "es": "Rustificar",
        "fr": "Rustifier",
        "de": "Rustifizieren",
    },
    "onboard_step4_desc": {
        "en": "🦀 Evaluates which Python functions could be rewritten in Rust for better performance, with side-by-side code previews.",
        "ro": "🦀 Evaluează ce funcții Python pot fi rescrise în Rust pentru performanță mai bună, cu preview-uri de cod.",
        "es": "🦀 Evalúa qué funciones Python podrían reescribirse en Rust, con vista previa del código.",
        "fr": "🦀 Évalue quelles fonctions Python pourraient être réécrites en Rust, avec aperçu du code.",
        "de": "🦀 Bewertet, welche Python-Funktionen in Rust umgeschrieben werden könnten, mit Code-Vorschau.",
    },
    "onboard_step5_title": {
        "en": "Scan & Explore Results",
        "ro": "Scanează & Explorează",
        "es": "Escanear y Explorar",
        "fr": "Analyser & Explorer",
        "de": "Scannen & Erkunden",
    },
    "onboard_step5_desc": {
        "en": "Press '⚡ Start Full Scan', then browse your results in tabs: grades, heatmaps, complexity charts, and code previews.",
        "ro": "Apasă '⚡ Începe Scanarea', apoi navighează rezultatele: note, hărți termice, grafice și cod.",
        "es": "Pulse '⚡ Iniciar Escaneo' y explore resultados: notas, mapas de calor, gráficos y código.",
        "fr": "Appuyez sur '⚡ Lancer l'Analyse' puis parcourez les résultats : notes, cartes, graphiques et code.",
        "de": "Drücken Sie '⚡ Scan Starten' und durchsuchen Sie Ergebnisse: Noten, Heatmaps, Diagramme und Code.",
    },
    "onboard_got_it": {
        "en": "Got it, let's go!",
        "ro": "Am înțeles, hai!",
        "es": "¡Entendido, vamos!",
        "fr": "Compris, allons-y !",
        "de": "Verstanden, los geht's!",
    },
    "onboard_next": {
        "en": "Next →",
        "ro": "Următorul →",
        "es": "Siguiente →",
        "fr": "Suivant →",
        "de": "Weiter →",
    },
    "onboard_back": {
        "en": "← Back",
        "ro": "← Înapoi",
        "es": "← Atrás",
        "fr": "← Retour",
        "de": "← Zurück",
    },
    "onboard_skip": {
        "en": "Skip",
        "ro": "Sari",
        "es": "Saltar",
        "fr": "Passer",
        "de": "Überspringen",
    },
    "language": {
        "en": "Language",
        "ro": "Limbă",
        "es": "Idioma",
        "fr": "Langue",
        "de": "Sprache",
    },
    # ── Thresholds ───────────────────────────────────────────────────────
    "thresholds": {
        "en": "Thresholds",
        "ro": "Praguri",
        "es": "Umbrales",
        "fr": "Seuils",
        "de": "Schwellenwerte",
    },
    "long_function": {
        "en": "Long function (lines)",
        "ro": "Funcție lungă (linii)",
        "es": "Función larga (líneas)",
        "fr": "Fonction longue (lignes)",
        "de": "Lange Funktion (Zeilen)",
    },
    "high_complexity": {
        "en": "High complexity (CC)",
        "ro": "Complexitate mare (CC)",
        "es": "Alta complejidad (CC)",
        "fr": "Haute complexité (CC)",
        "de": "Hohe Komplexität (CC)",
    },
    "deep_nesting": {
        "en": "Deep nesting (levels)",
        "ro": "Imbricare adâncă (nivele)",
        "es": "Anidamiento profundo",
        "fr": "Imbrication profonde",
        "de": "Tiefe Verschachtelung",
    },
    "too_many_params": {
        "en": "Too many params",
        "ro": "Prea mulți parametri",
        "es": "Demasiados parámetros",
        "fr": "Trop de paramètres",
        "de": "Zu viele Parameter",
    },
    "god_class": {
        "en": "God class (methods)",
        "ro": "Clasă-Dumnezeu (metode)",
        "es": "Clase Dios (métodos)",
        "fr": "Classe Dieu (méthodes)",
        "de": "Gott-Klasse (Methoden)",
    },
    # ── Complexity tab ───────────────────────────────────────────────────
    "avg_complexity": {
        "en": "Avg Complexity",
        "ro": "Complexitate Medie",
        "es": "Complejidad Promedio",
        "fr": "Complexité Moyenne",
        "de": "Mittlere Komplexität",
    },
    "max_complexity": {
        "en": "Max Complexity",
        "ro": "Complexitate Maximă",
        "es": "Complejidad Máxima",
        "fr": "Complexité Max",
        "de": "Max. Komplexität",
    },
    "most_complex": {
        "en": "Most Complex Functions",
        "ro": "Cele Mai Complexe Funcții",
        "es": "Funciones Más Complejas",
        "fr": "Fonctions les Plus Complexes",
        "de": "Komplexeste Funktionen",
    },
    "cc_distribution": {
        "en": "Complexity Distribution",
        "ro": "Distribuție Complexitate",
        "es": "Distribución Complejidad",
        "fr": "Distribution Complexité",
        "de": "Komplexitätsverteilung",
    },
    "size_distribution": {
        "en": "Size Distribution",
        "ro": "Distribuție Dimensiune",
        "es": "Distribución Tamaño",
        "fr": "Distribution Taille",
        "de": "Größenverteilung",
    },
    # ── Heatmap tab ──────────────────────────────────────────────────────
    "worst_files": {
        "en": "Worst Files",
        "ro": "Cele Mai Rele Fișiere",
        "es": "Peores Archivos",
        "fr": "Pires Fichiers",
        "de": "Schlechteste Dateien",
    },
    "issues_across": {
        "en": "issues across",
        "ro": "probleme în",
        "es": "problemas en",
        "fr": "problèmes dans",
        "de": "Probleme in",
    },
    # ── Pipeline ─────────────────────────────────────────────────────────
    "pipeline_config": {
        "en": "Pipeline Configuration",
        "ro": "Configurare Pipeline",
        "es": "Configuración Pipeline",
        "fr": "Configuration Pipeline",
        "de": "Pipeline-Konfiguration",
    },
    "build_mode": {
        "en": "Build mode",
        "ro": "Mod construire",
        "es": "Modo de compilación",
        "fr": "Mode de compilation",
        "de": "Build-Modus",
    },
    "min_score": {
        "en": "Min score",
        "ro": "Scor minim",
        "es": "Puntuación mínima",
        "fr": "Score minimum",
        "de": "Mindestpunktzahl",
    },
    "max_candidates": {
        "en": "Max candidates",
        "ro": "Maxim candidați",
        "es": "Máximo candidatos",
        "fr": "Max candidats",
        "de": "Max. Kandidaten",
    },
    "crate_name": {
        "en": "Crate name",
        "ro": "Nume crate",
        "es": "Nombre del crate",
        "fr": "Nom du crate",
        "de": "Crate-Name",
    },
    # ── Export ───────────────────────────────────────────────────────────
    "export": {
        "en": "Export",
        "ro": "Export",
        "es": "Exportar",
        "fr": "Exporter",
        "de": "Exportieren",
    },
    "penalties": {
        "en": "Penalties",
        "ro": "Penalizări",
        "es": "Penalizaciones",
        "fr": "Pénalités",
        "de": "Strafen",
    },
    "by_category": {
        "en": "By Category",
        "ro": "După Categorie",
        "es": "Por Categoría",
        "fr": "Par Catégorie",
        "de": "Nach Kategorie",
    },
    "all_issues": {
        "en": "All Issues",
        "ro": "Toate Problemele",
        "es": "Todos los Problemas",
        "fr": "Tous les Problèmes",
        "de": "Alle Probleme",
    },
    "filter_severity": {
        "en": "Filter by severity",
        "ro": "Filtrează după severitate",
        "es": "Filtrar por severidad",
        "fr": "Filtrer par sévérité",
        "de": "Nach Schwere filtern",
    },
    "issue": {
        "en": "Issue",
        "ro": "Problemă",
        "es": "Problema",
        "fr": "Problème",
        "de": "Problem",
    },
    "fix": {
        "en": "Fix",
        "ro": "Soluție",
        "es": "Solución",
        "fr": "Correction",
        "de": "Lösung",
    },
}


# ── Public API ───────────────────────────────────────────────────────────────


def set_locale(locale: str) -> None:
    """Set the active locale (e.g. ``"en"``, ``"ro"``)."""
    global _current_locale
    if locale in LOCALES:
        _current_locale = locale


def get_locale() -> str:
    """Return the current locale code."""
    return _current_locale


def t(key: str) -> str:
    """Look up a translated string for the current locale.

    Falls back to English if the key or locale is missing.
    """
    entry = _STRINGS.get(key)
    if entry is None:
        return key  # no translation at all — return the key name
    return entry.get(_current_locale, entry.get("en", key))
