import unittest
from pencere import topla

class TestTopla(unittest.TestCase):
    def test_topla_2_3(self):
        self.assertEqual(topla(2, 3), 5)

if __name__ == '__main__':
    unittest.main()