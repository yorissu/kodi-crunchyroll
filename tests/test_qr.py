"""The in-plugin QR encoder: every generated code must decode back to its text."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'plugin.video.crunchyrollqr', 'resources', 'lib'))
import qr  # noqa: E402

try:
	import zxingcpp
	from PIL import Image
except ImportError:
	zxingcpp = None


@unittest.skipIf(zxingcpp is None, 'needs zxing-cpp and pillow')
class QrTest(unittest.TestCase):
	def test_round_trip(self):
		# short (version 1), the activation URL (version 3), long (version 7+, has version info)
		for text in ('hi', 'https://www.crunchyroll.com/activate?code=lx7ql6', 'x' * 150):
			with tempfile.TemporaryDirectory() as tmp:
				path = qr.write_png(text, os.path.join(tmp, 'q.png'))
				with Image.open(path) as img:
					found = [b.text for b in zxingcpp.read_barcodes(img)]
			self.assertEqual(found, [text])


if __name__ == '__main__':
	unittest.main()
