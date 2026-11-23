"""Site CSV sync: verify safety checks and immutable archival."""
import tempfile
import unittest
from pathlib import Path
from sync_site_analyzer import validate_csv,save,secure_url

GOOD='回,口,数字1,数字2,数字3,数字4,数字5,数字6\n' + ''.join(
    '2158,{},{},{},{},{},{}\n'.format(i,i,i+1,i+2,i+3,i+4,i+5)
    for i in range(1,6)
)
# Six-number raw rows are deliberately supplied in the tests below.
def valid_data():
    lines=['回,口,数字1,数字2,数字3,数字4,数字5,数字6']
    for i in range(1,6):lines.append(f'2158,{i},{i},{i+1},{i+2},{i+3},{i+4},{i+5}')
    return ('\n'.join(lines)+'\n').encode('utf-8')

class SiteSyncTests(unittest.TestCase):
    def test_valid_import_and_idempotence(self):
        data=valid_data()
        rid,tickets=validate_csv(data)
        self.assertEqual(rid,2158)
        self.assertEqual(len(tickets),5)
        with tempfile.TemporaryDirectory() as tmp:
            dest=Path(tmp)
            self.assertEqual(save(data,dest)[0],'created')
            self.assertEqual(save(data,dest)[0],'unchanged')
            changed=data.replace(b'2158,1,1,2,3,4,5,6',b'2158,1,7,8,9,10,11,12')
            with self.assertRaises(RuntimeError):save(changed,dest)
    def test_bad_csv_rejected(self):
        with self.assertRaises(ValueError):validate_csv(valid_data()[:-14])
        with self.assertRaises(ValueError):validate_csv(valid_data().replace(b'2158,5',b'2159,5'))
    def test_host_restriction(self):
        self.assertTrue(secure_url('https://example.chatgpt.site/api/export.csv'))
        for url in ('http://example.chatgpt.site/export.csv',
                    'https://chatgpt.site/export.csv',
                    'https://example.chatgpt.site.evil.com/export.csv',
                    'https://x:abc@example.chatgpt.site/x'):
            with self.subTest(url=url),self.assertRaises(ValueError):secure_url(url)

if __name__=='__main__':unittest.main()
