"""Test that app imports and routes work"""
import sys
sys.path.insert(0, '.')
from app import app

print("=== App imported successfully ===")
print(f"Routes: {len(list(app.url_map.iter_rules()))}")
for rule in sorted(app.url_map.iter_rules(), key=lambda r: r.rule):
    print(f"  {rule.rule} -> {rule.endpoint}")
