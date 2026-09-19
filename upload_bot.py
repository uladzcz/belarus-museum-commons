#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Wikimedia Commons Automated Bot Uploader for Belarus Museum Catalog
===================================================================

This script allows direct, automated uploading of museum exhibits to
Wikimedia Commons using MediaWiki Bot Passwords.

Features:
1. Direct API upload via MediaWiki action=upload (no browser CORS limitations).
2. Standalone CLI: upload by exhibit ID or batch upload public domain exhibits.
3. Lightweight local HTTP bridge (--server) on http://127.0.0.1:5000:
   Enables 100% automated 1-click uploads directly from the web catalog!

Usage:
  # 1. Run as local bridge server for 1-click upload from browser:
  python upload_bot.py --server

  # 2. Upload single exhibit by ID:
  python upload_bot.py --id "cf36e121-48fc-4cd9-bd6c-c73c908250e2" --user "YourUser@BotName" --password "your_bot_password"

  # 3. Interactive mode:
  python upload_bot.py
"""

import sys
import os
import json
import argparse
import requests
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

API_URL = "https://commons.wikimedia.org/w/api.php"
USER_AGENT = "BelarusMuseumCatalogBot/1.0 (https://github.com/uladzcz/belarus-museum-commons; contact@uladzcz)"

class WikimediaCommonsUploader:
    def __init__(self, username, password):
        self.username = username
        self.password = password
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': USER_AGENT})
        self.csrf_token = None

    def login(self):
        """Authenticates with MediaWiki using Bot Password."""
        print(f"[*] Obtaining login token for {self.username}...")
        res = self.session.get(API_URL, params={
            'action': 'query',
            'meta': 'tokens',
            'type': 'login',
            'format': 'json'
        })
        res.raise_for_status()
        data = res.json()
        login_token = data.get('query', {}).get('tokens', {}).get('logintoken')
        if not login_token:
            raise RuntimeError(f"Could not obtain logintoken: {data}")

        print("[*] Logging in via MediaWiki API...")
        login_res = self.session.post(API_URL, data={
            'action': 'login',
            'lgname': self.username,
            'lgpassword': self.password,
            'lgtoken': login_token,
            'format': 'json'
        })
        login_res.raise_for_status()
        login_data = login_res.json()
        
        result = login_data.get('login', {}).get('result')
        if result != 'Success':
            reason = login_data.get('login', {}).get('reason', result)
            raise RuntimeError(f"MediaWiki login failed: {reason}")
        
        print("[+] Login successful!")

        # Obtain CSRF Token
        print("[*] Obtaining CSRF token...")
        csrf_res = self.session.get(API_URL, params={
            'action': 'query',
            'meta': 'tokens',
            'type': 'csrf',
            'format': 'json'
        })
        csrf_res.raise_for_status()
        csrf_data = csrf_res.json()
        self.csrf_token = csrf_data.get('query', {}).get('tokens', {}).get('csrftoken')
        if not self.csrf_token or len(self.csrf_token) < 5:
            raise RuntimeError(f"Could not obtain CSRF token: {csrf_data}")
        print("[+] CSRF token acquired successfully!")

    def upload_file(self, filename, wikitext, image_url_or_bytes, comment="Загрузка з Дзяржаўнага музейнага фонду Рэспублікі Беларусь (dkmf.by)"):
        """Uploads a file to Wikimedia Commons."""
        if not self.csrf_token:
            self.login()

        # Clean filename
        clean_filename = filename.replace('File:', '').strip()
        if not clean_filename.lower().endswith(('.jpg', '.jpeg', '.png', '.tif', '.tiff')):
            clean_filename += '.jpg'

        # Obtain file bytes
        if isinstance(image_url_or_bytes, bytes):
            file_bytes = image_url_or_bytes
        else:
            print(f"[*] Downloading image from {image_url_or_bytes}...")
            img_res = requests.get(image_url_or_bytes, headers={'User-Agent': USER_AGENT})
            img_res.raise_for_status()
            file_bytes = img_res.content

        print(f"[*] Uploading {clean_filename} ({len(file_bytes)} bytes) to Wikimedia Commons...")
        files = {
            'file': (clean_filename, file_bytes, 'image/jpeg')
        }
        data = {
            'action': 'upload',
            'filename': clean_filename,
            'text': wikitext,
            'token': self.csrf_token,
            'comment': comment,
            'ignorewarnings': '1',
            'format': 'json'
        }

        up_res = self.session.post(API_URL, data=data, files=files)
        up_res.raise_for_status()
        up_data = up_res.json()

        if 'error' in up_data:
            err = up_data['error']
            raise RuntimeError(f"Upload error: {err.get('info', err.get('code'))}")

        upload_result = up_data.get('upload', {})
        if upload_result.get('result') == 'Success':
            file_title = f"File:{upload_result.get('filename', clean_filename)}"
            commons_url = f"https://commons.wikimedia.org/wiki/{file_title.replace(' ', '_')}"
            print(f"[+] SUCCESS! Uploaded to Wikimedia Commons:\n    {commons_url}")
            return {
                'success': True,
                'fileTitle': file_title,
                'commonsUrl': commons_url
            }
        else:
            raise RuntimeError(f"Unexpected upload result: {up_data}")


class LocalBridgeHandler(BaseHTTPRequestHandler):
    """Local HTTP bridge for browser 1-click uploads."""
    def _set_headers(self, status=200):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        # Allow requests from GitHub Pages and localhost
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_OPTIONS(self):
        self._set_headers(200)

    def do_GET(self):
        if self.path == '/ping':
            self._set_headers(200)
            self.wfile.write(json.dumps({'status': 'ok', 'bot': 'BelarusMuseumCatalogBot'}).encode('utf-8'))
        else:
            self._set_headers(404)
            self.wfile.write(json.dumps({'error': 'Not found'}).encode('utf-8'))

    def do_POST(self):
        if self.path == '/upload':
            try:
                content_length = int(self.headers.get('Content-Length', 0))
                body = self.rfile.read(content_length)
                payload = json.loads(body.decode('utf-8'))

                username = payload.get('username')
                password = payload.get('password')
                filename = payload.get('suggestedFilename')
                wikitext = payload.get('wikitext')
                image_url = payload.get('imageUrl')

                if not username or not password:
                    self._set_headers(400)
                    self.wfile.write(json.dumps({'error': 'Username and Bot Password required'}).encode('utf-8'))
                    return

                uploader = WikimediaCommonsUploader(username, password)
                result = uploader.upload_file(filename, wikitext, image_url)

                self._set_headers(200)
                self.wfile.write(json.dumps(result).encode('utf-8'))
            except Exception as e:
                self._set_headers(500)
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
        else:
            self._set_headers(404)
            self.wfile.write(json.dumps({'error': 'Not found'}).encode('utf-8'))


def run_bridge_server(port=5000):
    server = HTTPServer(('127.0.0.1', port), LocalBridgeHandler)
    print(f"\n=======================================================")
    print(f"🚀 Беларускі музейны робат для Вікісховішча запушчаны!")
    print(f"   Адрас: http://127.0.0.1:{port}")
    print(f"   Цяпер пры націсканні кнопкі «1-Клік загрузка» на сайце")
    print(f"   файл будзе АЎТАМАТЫЧНА загружацца праз гэты скрыпт!")
    print(f"=======================================================\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[*] Спыненне робата...")
        server.server_close()


def main():
    parser = argparse.ArgumentParser(description="Wikimedia Commons Uploader for Belarus Museum Catalog")
    parser.add_argument("--server", action="store_true", help="Start local bridge server on port 5000 for browser 1-click upload")
    parser.add_argument("--port", type=int, default=5000, help="Port for bridge server (default: 5000)")
    parser.add_argument("--id", type=str, help="Exhibit ID to upload")
    parser.add_argument("--user", type=str, help="Wikimedia username/bot name (e.g. User@Bot)")
    parser.add_argument("--password", type=str, help="Bot Password")

    args = parser.parse_args()

    if args.server:
        run_bridge_server(args.port)
    elif args.id:
        username = args.user or input("Увядзіце імя бота на Вікісховішчы (напрыклад, Uladzcz@CatalogBot): ")
        password = args.password or input("Увядзіце Bot Password: ")
        uploader = WikimediaCommonsUploader(username, password)
        # Load exhibit from exhibits.json
        exhibits_path = os.path.join(os.path.dirname(__file__), "exhibits.json")
        if os.path.exists(exhibits_path):
            with open(exhibits_path, "r", encoding="utf-8") as f:
                exhibits = json.load(f)
            target = next((e for e in exhibits if e.get("id") == args.id), None)
            if not target:
                print(f"[-] Экспанат з ID {args.id} не знойдзены.")
                return
            img_url = target.get("imgOriginal") or target.get("imgMedium")
            filename = target.get("nameRu", "Exhibit") + ".jpg"
            name_be = target.get('nameBe', '')
            name_ru = target.get('nameRu', '')
            wikitext = "== {{int:filedesc}} ==\n{{Artwork\n|title = {{be|" + name_be + "}}{{ru|" + name_ru + "}}\n}}"
            uploader.upload_file(filename, wikitext, img_url)
        else:
            print(f"[-] exhibits.json не знойдзены.")
    else:
        print("Запуск лакальнага моста робата для каталога...")
        run_bridge_server(args.port)


if __name__ == "__main__":
    main()
