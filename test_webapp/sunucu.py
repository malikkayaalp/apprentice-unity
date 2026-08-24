import http.server
import json
import os
import urllib.parse


class BasitHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == "/":
            # arayuz.html dosyasını sunucu.py ile aynı klasörden oku
            dosya_yolu = os.path.join(os.path.dirname(os.path.abspath(__file__)), "arayuz.html")
            try:
                with open(dosya_yolu, "r", encoding="utf-8") as f:
                    icerik = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(icerik.encode("utf-8"))
            except FileNotFoundError:
                self.send_response(404)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write("arayuz.html bulunamadı.".encode("utf-8"))
        elif path == "/api/topla":
            sorgu = urllib.parse.parse_qs(parsed.query)
            a_str = sorgu.get("a", [None])[0]
            b_str = sorgu.get("b", [None])[0]

            if a_str is None or b_str is None:
                self.send_response(400)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"hata": "Eksik parametre: 'a' ve 'b' gerekli."}).encode("utf-8"))
                return

            try:
                a = float(a_str)
                b = float(b_str)
            except ValueError:
                self.send_response(400)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"hata": "Geçersiz parametre: 'a' ve 'b' sayı olmalı."}).encode("utf-8"))
                return

            sonuc = a + b
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({"sonuc": sonuc}).encode("utf-8"))
        else:
            self.send_response(404)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write("Bulunamadı.".encode("utf-8"))

    def log_message(self, format, *args):
        # Varsayılan loglama kapalı (testlerde gürültü olmasın)
        pass


def baslat(port=0):
    sunucu = http.server.HTTPServer(("", port), BasitHandler)
    return sunucu


if __name__ == "__main__":
    sunucu = baslat(port=8765)
    print("Sunucu 8765 portunda başlatıldı. Kapatmak için Ctrl+C yapın.")
    sunucu.serve_forever()
