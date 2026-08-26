import frappe
import requests
from lex.lex.doctype.lpo_ai_settings.lpo_ai_settings import _get_provider_key

def execute():
    key = _get_provider_key(None, 'Google Gemini')
    if not key:
        print("No key found!")
        return
        
    url = f'https://generativelanguage.googleapis.com/v1beta/models?key={key}'
    r = requests.get(url)
    print(f"Status: {r.status_code}")
    data = r.json()
    valid_models = []
    for m in data.get("models", []):
        methods = m.get("supportedGenerationMethods", [])
        if "generateContent" in methods:
            valid_models.append(m.get("name"))
    print("Valid generateContent models:", valid_models)
