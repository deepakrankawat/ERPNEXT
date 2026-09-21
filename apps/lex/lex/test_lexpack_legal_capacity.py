import unittest

from lex.lexpack import calculate_legal_capacity


class TestLegalCapacity(unittest.TestCase):
	def test_legal_capacity_uses_discount_against_normal_work_price(self):
		self.assertEqual(calculate_legal_capacity(1000, 7), 1075.27)
		self.assertEqual(calculate_legal_capacity(1000, 14), 1162.79)
		self.assertEqual(calculate_legal_capacity(1000, 21), 1265.82)
		self.assertEqual(calculate_legal_capacity(1000, 28), 1388.89)

	def test_legal_capacity_rejects_invalid_discount(self):
		with self.assertRaises(Exception):
			calculate_legal_capacity(1000, 100)
