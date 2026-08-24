import unittest
import urllib.request
import urllib.error
import json
import threading
import time

from test_webapp.sunucu import baslat


class TestSunucu(unittest.TestCase):
    def setUp(self):
        self.sunucu = baslat(port=0)
        port = self.sunucu.server_address[1]
        self.base_url = f"http://127.0.0.1:{port}"
        self.thread = threading.Thread(target=self.sunucu.serve_forever)
        self.thread.daemon = True
        self.thread.start()
        # Sunucunun başlaması için kısa bekleyiş
        time.sleep(0.1)

    def tearDown(self):
        self.sunucu.shutdown()
        self.thread.join(timeout=1)

    def test_api_topla_2_ve_3(self):
        url = self.base_url + "/api/topla?a=2&b=3"
        with urllib.request.urlopen(url) as response:
            self.assertEqual(response.status, 200)
            data = json.loads(response.read().decode("utf-8"))
            self.assertEqual(data["sonuc"], 5.0)

    def test_api_topla_gecersiz_parametre(self):
        url = self.base_url + "/api/topla?a=x"
        try:
            urllib.request.urlopen(url)
            self.fail("400 bekleniyordu, ancak başarı alındı.")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 400)
            data = json.loads(e.read().decode("utf-8"))
            self.assertIn("hata", data)

    def test_anasayfa_html_id_topla(self):
        url = self.base_url + "/"
        with urllib.request.urlopen(url) as response:
            self.assertEqual(response.status, 200)
            icerik = response.read().decode("utf-8")
            self.assertIn('id="topla"', icerik)


if __name__ == "__main__":
    unittest.main()
