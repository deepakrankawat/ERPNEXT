import frappe
from lex.lex.doctype.lpo_ai_settings.lpo_ai_settings import _get_provider_key
import requests

def execute():
    key = _get_provider_key(None, 'Google Gemini')
    print('Key:', key[:10] if key else 'None')
    if key:
        for m in ['gemini-1.5-pro', 'gemini-1.5-flash', 'gemini-3.1-pro']:
            url = f'https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={key}'
            try:
                r = requests.post(url, json={'contents': [{'parts': [{'text': 'hi'}]}]}, headers={'Content-Type': 'application/json'})
                print(m, '=>', r.status_code, r.text[:150])
            except Exception as e:
                print(m, 'Exception:', e)
