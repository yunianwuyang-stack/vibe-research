from pathlib import Path
def test_editorial_design_tokens_theme_accessibility_and_responsive_shell():
 css=(Path(__file__).resolve().parents[1]/'frontend/src/styles.css').read_text();assert '--space:8px' in css and 'prefers-color-scheme:dark' in css and 'focus-visible' in css and 'max-width:1024px' in css and 'prefers-reduced-motion' in css
