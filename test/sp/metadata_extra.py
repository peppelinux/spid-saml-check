import lxml.objectify
import os
import requests
import sys
import time
import unittest
import validators
import warnings
import urllib.parse

from io import BytesIO
from lxml import etree as ET

METADATA = os.getenv('METADATA', None)
SSLLABS_SKIP = int(os.getenv('SSLLABS_SKIP', 0))


API = 'https://api.ssllabs.com/api/v2/'


def ssllabs_api(path, payload={}):
    url = API + path

    try:
        response = requests.get(url, params=payload)
    except requests.exception.RequestException:
        sys.stderr.write('Request failed.')
        sys.exit(1)

    data = response.json()
    return data


def ssllabs_from_cache(host, publish='off', startNew='off', fromCache='on',
                       all='done'):
    path = 'analyze'
    payload = {
                'host': host,
                'publish': publish,
                'startNew': startNew,
                'fromCache': fromCache,
                'all': all
              }
    data = ssllabs_api(path, payload)
    return data


def ssllabs_new_scan(host, publish='off', startNew='on', all='done',
                     ignoreMismatch='on'):
    path = 'analyze'
    payload = {
                'host': host,
                'publish': publish,
                'startNew': startNew,
                'all': all,
                'ignoreMismatch': ignoreMismatch
              }
    results = ssllabs_api(path, payload)

    payload.pop('startNew')

    while results['status'] != 'READY' and results['status'] != 'ERROR':
        time.sleep(30)
        results = ssllabs_api(path, payload)

    return results


def del_ns(tree):
    root = tree.getroot()
    for elem in root.getiterator():
        if not hasattr(elem.tag, 'find'):
            continue
        i = elem.tag.find('}')
        if i >= 0:
            elem.tag = elem.tag[i+1:]
    lxml.objectify.deannotate(root, cleanup_namespaces=True)


class TestSPMetadataExtra(unittest.TestCase):

    def setUp(self):
        if not METADATA:
            self.fail('METADATA not set')

        with open(METADATA, 'rb') as md_file:
            md = md_file.read()
            self.doc = ET.parse(BytesIO(md))
            md_file.close()

        warnings.filterwarnings(
            action="ignore",
            message="unclosed",
            category=ResourceWarning
        )

    def tearDown(self):
        warnings.filterwarnings(
            action="ignore",
            message="unclosed",
            category=ResourceWarning
        )

    def test_entityID(self):
        del_ns(self.doc)

        ed = self.doc.xpath('//EntityDescriptor')[0]
        eid = ed.get('entityID')

        with self.subTest('entityID must be an HTTPS uri'):
            self.assertTrue(eid.startswith('https://'))
            self.assertTrue(validators.url(eid))

    def test_SPSSODescriptor(self):
        del_ns(self.doc)

        spsso = self.doc.xpath('//EntityDescriptor/SPSSODescriptor')

        with self.subTest('protocolSuportEnumeration must be '
                          'urn:oasis:names:tc:SAML:2.0:protocol'):
            pse = spsso[0].get('protocolSupportEnumeration')
            self.assertEqual(pse, 'urn:oasis:names:tc:SAML:2.0:protocol')

        with self.subTest('WantAssertionsSigned must be true'):
            was = spsso[0].get('WantAssertionsSigned')
            self.assertEqual(was, 'true')

    def test_Organization(self):
        del_ns(self.doc)

        org = self.doc.xpath('//EntityDescriptor/Organization')[0]

        with self.subTest('must have OrganizationName localized as IT'):
            oname = org.xpath(
                './OrganizationName[@xml:lang="it"]',
                namespaces={
                    'xml': 'http://www.w3.org/XML/1998/namespace',
                }
            )
            self.assertEqual(len(oname), 1)

        with self.subTest('must have OrganizationURL localized as IT'):
            ourl = org.xpath(
                './OrganizationURL[@xml:lang="it"]',
                namespaces={
                    'xml': 'http://www.w3.org/XML/1998/namespace',
                }
            )
            self.assertEqual(len(ourl), 1)

        with self.subTest('must have OrganizationDisplayName localized as IT'):
            odn = org.xpath(
                './OrganizationDisplayName[@xml:lang="it"]',
                namespaces={
                    'xml': 'http://www.w3.org/XML/1998/namespace',
                }
            )
            self.assertEqual(len(odn), 1)

    @unittest.skipIf(SSLLABS_SKIP == 1, 'x')
    def test_ssllabs(self):
        del_ns(self.doc)

        locations = []
        c = 0
        acss = self.doc.xpath('//EntityDescriptor/SPSSODescriptor'
                              '/AssertionConsumerService')
        for acs in acss:
            url = acs.get('Location')
            locations.append(url)

        to_check = [(urllib.parse.urlparse(location).netloc, location)
                    for location in locations]
        for t in to_check:
            data = ssllabs_from_cache(t[0])
            while data['status'] != 'ERROR' and data['status'] != 'READY':
                time.sleep(30)
                data = ssllabs_from_cache(t[0])

            if data['status'] == 'ERROR':
                c += 1
                msg = (('[ERROR] AssertionConsumerService, %s, (%s)') %
                       (t[1], data['statusMessage']))
                sys.stderr.write('\n\t%s' % msg)
            elif data['status'] == 'READY':
                grade = data['endpoints'][0]['grade']
                msg = '[%s] AssertionConsumerService, %s' % (grade, t[1])
                sys.stderr.write('\n\t%s' % msg)
                if grade not in ['A+', 'A', 'A-']:
                    c += 1
            else:
                sys.stderr.write('\n\t%s' % data['status'])
                pass

        locations = []
        slos = self.doc.xpath('//EntityDescriptor/SPSSODescriptor'
                              '/SingleLogoutService')
        for slo in slos:
            url = slo.get('Location')
            locations.append(url)

        to_check = [(urllib.parse.urlparse(location).netloc, location)
                    for location in locations]
        for t in to_check:
            data = ssllabs_from_cache(t[0])
            while data['status'] != 'ERROR' and data['status'] != 'READY':
                time.sleep(30)
                data = ssllabs_from_cache(t[0])

            if data['status'] == 'ERROR':
                c += 1
                msg = (('[ERROR] SingleLogoutService, %s, (%s)') %
                       (t[1], data['statusMessage']))
                sys.stderr.write('\n\t%s' % msg)
            elif data['status'] == 'READY':
                grade = data['endpoints'][0]['grade']
                msg = '[%s] SingleLogoutService, %s' % (grade, t[1])
                sys.stderr.write('\n\t%s' % msg)
                if grade not in ['A+', 'A', 'A-']:
                    c += 1
            else:
                sys.stderr.write('\n\t%s' % data['status'])
                pass

        sys.stderr.write('\n')
        self.assertEqual(
            c,
            0,
            'One or more AssertionConsumerService/ServiceLogoutService URLs '
            'have weak TLS configuration or are not reachable'
        )
