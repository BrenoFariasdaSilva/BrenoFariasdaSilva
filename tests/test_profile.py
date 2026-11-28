import datetime as dt
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

SPEC = importlib.util.spec_from_file_location('profile_tools', Path(__file__).parents[1] / 'scripts' / 'profile.py')
profile = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(profile)
GOOD = b'<svg xmlns="http://www.w3.org/2000/svg"><text>Healthy card</text></svg>'
BAD = b'<svg xmlns="http://www.w3.org/2000/svg"><text>Something went wrong</text></svg>'


class ProfileTests(unittest.TestCase):
    def test_svg_valid(self):
        self.assertEqual(profile.valid_svg(GOOD).tag, profile.SVG_NS + 'svg')

    def test_error_card(self):
        with self.assertRaises(ValueError):
            profile.valid_svg(BAD)

    def test_non_svg(self):
        with self.assertRaises(ValueError):
            profile.valid_svg(b'<html>error</html>')
        with self.assertRaises(ET.ParseError):
            profile.valid_svg(b'bad data')

    def test_empty_svg(self):
        with self.assertRaises(ValueError):
            profile.valid_svg(b'<svg xmlns="http://www.w3.org/2000/svg"/>')

    def test_update_only_selected_section(self):
        text = 'before\n<!--START_SECTION:activity-->\nold\n<!--END_SECTION:activity-->\n<!--START_SECTION:waka-->\nkeep\n<!--END_SECTION:waka-->\n'
        expected = text.replace('\nold\n', '\nnew\n')
        self.assertEqual(profile.update_section(text, 'activity', 'new'), expected)
        with self.assertRaises(ValueError):
            profile.update_section(text, 'missing', 'new')
        with self.assertRaises(ValueError):
            profile.update_section(text+text, 'activity', 'new')

    def test_activity_avoids_private_and_profile_events(self):
        public = {'type':'PushEvent','public':True,'repo':{'name':'owner/repo'}}
        events = [public, public, {'type':'PushEvent','public':False,'repo':{'name':'owner/secret'}},
                  {'type':'PushEvent','public':True,'repo':{'name':'owner/owner'}},
                  {'type':'PullRequestEvent','public':True,'repo':{'name':'other/repo'},'payload':{'action':'opened','pull_request':{'number':7}}}]
        lines = profile.activity_lines(events, 'owner')
        self.assertEqual(len(lines), 2)
        self.assertIn('Pushed to [owner/repo]', lines[0])
        self.assertIn('/pull/7', lines[1])
        self.assertNotIn('secret', '\n'.join(lines))

    def test_calendar_and_graph(self):
        today = dt.date(2026, 11, 28)
        weeks = [{'contributionDays':[{'date':(today-dt.timedelta(days=i)).isoformat(),'contributionCount':i % 4} for i in range(30)]}]
        dates, counts = profile.calendar_series(weeks, today)
        self.assertEqual(len(dates), 30)
        self.assertEqual(dates[-1], today)
        self.assertEqual(counts[-1], 0)
        for svg in profile.graph_svgs(dates, counts):
            profile.valid_svg(svg.encode())
        self.assertIn(str(sum(counts)), profile.graph_svgs(dates, counts)[1])

    def test_calendar_missing_today(self):
        today = dt.date(2026, 11, 28)
        weeks = [{'contributionDays':[{'date':(today-dt.timedelta(days=i)).isoformat(),'contributionCount':0} for i in range(1,30)]}]
        dates, counts = profile.calendar_series(weeks, today)
        self.assertEqual(len(dates), 29)
        profile.valid_svg(profile.graph_svgs(dates, counts)[0].encode())
        with self.assertRaises(ValueError):
            profile.calendar_series([], today)

    def test_publish_retains_last_good(self):
        with tempfile.TemporaryDirectory() as folder:
            source, dest = Path(folder)/'source', Path(folder)/'dest'
            source.mkdir(); dest.mkdir()
            (source/'github-stats.svg').write_bytes(GOOD)
            (source/'streak.svg').write_bytes(BAD)
            (dest/'streak.svg').write_bytes(GOOD)
            text = '![Stats](https://github-readme-stats.vercel.app/api?username=owner)\n![Streak](profile/streak.svg)'
            updated, invalid = profile.publish_cards(text, source, dest)
            self.assertIn('![Stats](profile/github-stats.svg)', updated)
            self.assertIn('![Streak](profile/streak.svg)', updated)
            self.assertEqual((dest/'streak.svg').read_bytes(), GOOD)
            self.assertIn('streak.svg', invalid)
            self.assertNotIn('github-stats.svg', invalid)

    def test_publish_all_cards(self):
        with tempfile.TemporaryDirectory() as folder:
            source, dest = Path(folder)/'source', Path(folder)/'dest'
            source.mkdir()
            for name in profile.MAPPINGS:
                (source/name).write_bytes(GOOD)
            updated, invalid = profile.publish_cards('<!-- profile-analytics -->', source, dest)
            self.assertFalse(invalid)
            self.assertIn('profile/analytics.svg', updated)
            self.assertEqual(set(p.name for p in dest.iterdir()), set(profile.MAPPINGS))

    def test_image_references(self):
        text = '<picture><source media="dark" srcset="dark.svg"><img src="light.svg"></picture>\n[![Card](card.svg)](https://example.com)'
        self.assertEqual(profile.image_urls(text), ['card.svg','dark.svg','light.svg'])

    def test_remote_validation(self):
        with patch.object(profile, 'request', return_value=GOOD):
            self.assertIsNone(profile.validate_remote('https://example.com/card.svg'))
        with patch.object(profile, 'request', return_value=BAD):
            self.assertIsNotNone(profile.validate_remote('https://example.com/card.svg'))
        with patch.object(profile, 'request', return_value=b'GIF89a'+b'x'*20):
            self.assertIsNone(profile.validate_remote('https://example.com/image.gif'))
        with patch.object(profile, 'request', return_value=b'<html>Not an image</html>'):
            self.assertIsNotNone(profile.validate_remote('https://example.com/'))


if __name__ == '__main__':
    unittest.main()
