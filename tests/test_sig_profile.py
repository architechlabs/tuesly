import unittest
from test_transport import COMPONENT
from tuesly_mesh.sig_profile import light_profile
from tuesly_mesh.sig_mesh_protocol_codec import config_model_app_bind

class ProfileTests(unittest.TestCase):
    def test_measured_tuya_uuid_needs_no_fixture_label(self):
        result=light_profile('DC:23:52:81:60:BB',bytes.fromhex('dc23528160bb5112626c6274746267790000'))
        self.assertTrue(result['tunable_white'])
        self.assertEqual(result['product_type'],2)

    def test_unrelated_or_truncated_uuid_is_not_claimed(self):
        for raw in (b'',b'\0'*18,bytes.fromhex('aaaaaaaaaaaa5112626c6274746267790000')):
            self.assertIsNone(light_profile('DC:23:52:81:60:BB',raw))

    def test_vendor_binding_uses_company_then_model_little_endian(self):
        self.assertEqual(config_model_app_bind(1022,0,4,0x07d0).hex(),'803dfe030000d0070400')
        self.assertEqual(config_model_app_bind(1022,0,5,0x07d0).hex(),'803dfe030000d0070500')
