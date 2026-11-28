"""Generate, publish and validate profile SVGs using only the standard library."""
import datetime as dt
import html
import json
import os
from pathlib import Path
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / 'README.md'
USER = os.getenv('PROFILE_USER', 'BrenoFariasdaSilva')
CARD_DIR = Path(os.getenv('CARD_DIR', str(ROOT / 'profile')))
SVG_NS = '{http://www.w3.org/2000/svg}'
ERRORS = ('something went wrong', 'could not fetch', 'rate limit exceeded', 'failed to fetch',
          'invalid username', 'user not found', 'an error occurred', 'maximum retries exceeded',
          'please re-authorize', 'please reauthorize', 'authorization required', 'not connected')
MAPPINGS = {
    'github-stats.svg': r'https://github-readme-stats\.vercel\.app/api\?[^"\s)]+',
    'top-languages.svg': r'https://github-readme-stats\.vercel\.app/api/top-langs/\?[^"\s)]+',
    'streak.svg': r'https://streak-stats\.demolab\.com/\?[^"\s)]+',
    'trophies.svg': r'https://github-profile-trophy\.vercel\.app/\?[^"\s)]+',
    'activity.svg': r'https://github-readme-activity-graph\.vercel\.app/graph\?[^"\s)]+',
    'analytics.svg': None,
}


def request(url, payload=None, authenticated=True):
    headers = {'User-Agent': 'profile-readme-validator'}
    if authenticated:
        headers['Authorization'] = 'Bearer ' + os.environ['GH_TOKEN']
        headers['Accept'] = 'application/vnd.github+json'
    else:
        headers['Accept'] = 'image/*,*/*;q=0.1'
    if payload is not None:
        headers['Content-Type'] = 'application/json'
    req = urllib.request.Request(url, data=None if payload is None else json.dumps(payload).encode(), headers=headers)
    with urllib.request.urlopen(req, timeout=25) as response:
        data = response.read(10_000_001)
        if len(data) > 10_000_000:
            raise ValueError('Response exceeds 10 MB')
        return data


def valid_svg(data):
    root = ET.fromstring(data)
    if root.tag != SVG_NS + 'svg':
        raise ValueError('Not an SVG document')
    text = ' '.join(root.itertext()).lower()
    if any(error in text for error in ERRORS):
        raise ValueError('Service returned an error card')
    if not list(root):
        raise ValueError('Empty SVG')
    return root


def update_section(text, section, replacement):
    pattern = re.compile(r'(<!--START_SECTION:' + re.escape(section) + r'-->)[\s\S]*?(<!--END_SECTION:' + re.escape(section) + r'-->)')
    result, count = pattern.subn(lambda m: m[1] + '\n' + replacement.strip() + '\n' + m[2], text)
    if count != 1:
        raise ValueError('Expected exactly one section: ' + section)
    return result


def activity_lines(events, user=USER):
    lines, seen = [], set()
    for event in events:
        name = event.get('repo', {}).get('name', '')
        if not re.fullmatch(r'[\w.-]+/[\w.-]+', name) or name.lower() == (user + '/' + user).lower():
            continue
        if event.get('public') is False:
            continue
        kind, payload = event.get('type'), event.get('payload', {})
        base = 'https://github.com/' + name
        number = None
        if kind == 'PushEvent':
            verb, href = 'Pushed to', base
        elif kind in ('PullRequestEvent', 'IssuesEvent', 'IssueCommentEvent'):
            number = (payload.get('pull_request') or payload.get('issue') or {}).get('number')
            if not isinstance(number, int):
                continue
            noun = {'PullRequestEvent': 'pull request', 'IssuesEvent': 'issue', 'IssueCommentEvent': 'issue discussion'}[kind]
            action = payload.get('action', '')
            verb = (action.capitalize() if action in ('opened', 'closed', 'reopened', 'created', 'edited') else 'Updated') + ' ' + noun
            href = base + ('/pull/' if kind == 'PullRequestEvent' else '/issues/') + str(number)
        elif kind == 'ReleaseEvent':
            verb, href = 'Published or updated a release in', base + '/releases'
        else:
            continue
        key = kind, name, number, verb
        if key in seen:
            continue
        seen.add(key)
        lines.append(f"{len(lines)+1}. {verb} [{name}{' #' + str(number) if number else ''}]({href})")
        if len(lines) == 8:
            break
    return lines


def activity():
    events = json.loads(request('https://api.github.com/users/' + urllib.parse.quote(USER) + '/events/public?per_page=100'))
    if not isinstance(events, list):
        raise ValueError('Expected a list of public events')
    lines = activity_lines(events)
    README.write_text(update_section(README.read_text(), 'activity', '\n'.join(lines) or 'No matching public activity in the recent GitHub event feed.'))


def calendar_series(weeks, today):
    by_date = {dt.date.fromisoformat(day['date']): day['contributionCount']
               for week in weeks for day in week['contributionDays']}
    dates = [today - dt.timedelta(days=offset) for offset in range(29, -1, -1)]
    if any(day not in by_date for day in dates[:-1]):
        raise ValueError('Incomplete historical contribution calendar')
    if dates[-1] not in by_date:
        dates.pop()
    counts = [by_date[date] for date in dates]
    if not counts or any(type(value) is not int or value < 0 for value in counts):
        raise ValueError('Invalid contribution calendar')
    return dates, counts


def graph_svgs(dates, counts):
    step = max(1, (max(counts) + 3) // 4)
    maximum = 4 * step
    body = ['<rect width="800" height="265" rx="8" fill="#1a1b26"/>',
            '<text x="24" y="34" fill="#7aa2f7" font-size="19" font-weight="bold">GitHub contribution activity</text>',
            '<text x="24" y="54" fill="#a9b1d6" font-size="12">Daily contributions visible to the configured GitHub token</text>']
    for i in range(5):
        y = 205 - i * 33
        body += [f'<path d="M60 {y} H780" stroke="#30344a"/>',
                 f'<text x="53" y="{y+4}" fill="#a9b1d6" font-size="11" text-anchor="end">{step*i}</text>']
    for i, (date, count) in enumerate(zip(dates, counts)):
        x, w = 64 + i * 710 / len(dates), 710 / len(dates) - 5
        h = count / maximum * 132
        body.append(f'<rect x="{x:.2f}" y="{205-h:.2f}" width="{w:.2f}" height="{h:.2f}" rx="2" fill="#7aa2f7"><title>{date}: {count} contributions</title></rect>')
        if i % 5 == 0 or i == len(dates)-1:
            body.append(f'<text x="{x+w/2:.2f}" y="225" font-size="9" fill="#a9b1d6" text-anchor="middle">{date:%m/%d}</text>')
    body.append(f'<text x="24" y="249" font-size="11" fill="#a9b1d6">{dates[0]} to {dates[-1]} · latest UTC day may be partial</text>')
    graph = '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="265" viewBox="0 0 800 265" role="img" aria-label="Recent contribution activity" font-family="Verdana,Arial,sans-serif">' + ''.join(body) + '</svg>\n'
    active = sum(count > 0 for count in counts)
    stats = [('Contributions', sum(counts)), ('Active days', f'{active}/{len(counts)}'), ('Peak day', max(counts))]
    cells = []
    for i, (label, value) in enumerate(stats):
        x = 133 + 267*i
        cells.append(f'<text x="{x}" y="63" text-anchor="middle" fill="#a9b1d6" font-size="13">{label}</text><text x="{x}" y="99" text-anchor="middle" fill="#7aa2f7" font-weight="bold" font-size="26">{value}</text>')
    summary = '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="140" viewBox="0 0 800 140" role="img" aria-label="Recent GitHub contribution summary" font-family="Verdana,Arial,sans-serif"><rect width="800" height="140" rx="8" fill="#1a1b26"/><text x="24" y="30" fill="#7aa2f7" font-weight="bold" font-size="17">Recent contribution summary</text>' + ''.join(cells) + f'<text x="400" y="126" text-anchor="middle" font-size="11" fill="#a9b1d6">{dates[0]} to {dates[-1]} · visible contributions</text></svg>\n'
    return graph, summary


def graph():
    query = '''query($login: String!) { user(login: $login) { contributionsCollection {
      contributionCalendar { weeks { contributionDays { date contributionCount } } }
    } } }'''
    result = json.loads(request('https://api.github.com/graphql', {'query':query, 'variables':{'login':USER}}))
    if result.get('errors'):
        raise ValueError('GitHub GraphQL query failed')
    weeks = result['data']['user']['contributionsCollection']['contributionCalendar']['weeks']
    dates, counts = calendar_series(weeks, dt.datetime.now(dt.timezone.utc).date())
    CARD_DIR.mkdir(parents=True, exist_ok=True)
    for name, svg in zip(('activity.svg', 'analytics.svg'), graph_svgs(dates, counts)):
        valid_svg(svg.encode())
        (CARD_DIR / name).write_text(svg)


# Classic flat badge dimensions (20 px high), with a white WakaTime icon.
# Widths are conservative 11 px sans-serif glyph advances, in tenths of a pixel.
# Keeping these local makes SVG generation deterministic without font dependencies.
WAKA_LOGO_PATH = ('M12 0C5.373 0 0 5.373 0 12s5.373 12 12 12 12-5.373 12-12S18.627 0 12 0zm0 2.824a9.176 9.176 0 1 1 0 18.352 9.176 9.176 0 0 1 0-18.352zm5.097 5.058c-.327 0-.61.19-.764.45-1.025 1.463-2.21 3.162-3.288 4.706l-.387-.636a.897.897 0 0 0-.759-.439.901.901 0 0 0-.788.492l-.357.581-1.992-2.943a.897.897 0 0 0-.761-.446c-.514 0-.903.452-.903.96a1 1 0 0 0 .207.61l2.719 3.96c.152.272.44.47.776.47a.91.91 0 0 0 .787-.483c.046-.071.23-.368.314-.504l.324.52c-.035-.047.076.113.087.13.024.031.054.059.078.085.019.019.04.036.058.052.036.033.08.056.115.08.025.016.052.028.076.04.029.015.06.024.088.035.058.025.122.027.18.04.031.004.064.003.092.005.29 0 .546-.149.707-.36 1.4-2 2.842-4.055 4.099-5.849A.995.995 0 0 0 18 8.842c0-.508-.389-.96-.903-.96')
WAKA_GLYPH_WIDTHS = {' ': 35, ',': 35, '.': 35, ':': 37,
                     'h': 70, 'r': 46, 's': 58, 'm': 108, 'i': 31,
                     'n': 70, 'd': 70, 'a': 68, 'y': 66, 'e': 68,
                     'c': 61, 'o': 68, 'w': 90, 'k': 64}


def waka_badge_svg(total):
    """Render a compact classic-style badge for the actual all-time total."""
    total = total.strip()
    if not total:
        raise ValueError('WakaTime total is empty')
    label_width = 81
    # Five pixels of padding on each side, plus the actual value width.
    text_width = (sum(70 if char.isascii() and char.isdigit() else
                      WAKA_GLYPH_WIDTHS.get(char, 110) for char in total) + 9) // 10
    value_width = text_width + 10
    width = label_width + value_width
    value_x = label_width + value_width / 2
    value = html.escape(total)
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="20" viewBox="0 0 {width} 20" role="img" aria-label="wakatime: {value}">
  <title>wakatime: {value}</title>
  <defs>
    <linearGradient id="shade" x2="0" y2="100%">
      <stop offset="0" stop-color="#bbb" stop-opacity=".1"/>
      <stop offset="1" stop-opacity=".1"/>
    </linearGradient>
    <clipPath id="round"><rect width="{width}" height="20" rx="3"/></clipPath>
  </defs>
  <g clip-path="url(#round)">
    <rect width="{label_width}" height="20" fill="#555"/>
    <rect x="{label_width}" width="{value_width}" height="20" fill="#3778b8"/>
    <rect width="{width}" height="20" fill="url(#shade)"/>
  </g>
  <path d="{WAKA_LOGO_PATH}" fill="#fff" transform="translate(5 3) scale(0.5833333333)"/>
  <g font-family="Verdana,Geneva,DejaVu Sans,sans-serif" font-size="11" text-anchor="middle">
    <g fill="#010101" opacity=".3" aria-hidden="true">
      <text x="48" y="15">wakatime</text>
      <text x="{value_x:g}" y="15">{value}</text>
    </g>
    <g fill="#fff">
      <text x="48" y="14">wakatime</text>
      <text x="{value_x:g}" y="14">{value}</text>
    </g>
  </g>
</svg>
'''


def refresh_waka_badge(text):
    section = re.search(r'<!--START_SECTION:waka-->([\s\S]*?)<!--END_SECTION:waka-->', text)
    total = re.search(r'^Total Time: (.+)$', section[1], re.M) if section else None
    if not total or not total[1].strip():
        return
    badge = waka_badge_svg(total[1])
    valid_svg(badge.encode())
    (ROOT / 'badges' / 'wakatime.svg').write_text(badge)


def publish_cards(text, source, destination):
    invalid = []
    for filename, pattern in MAPPINGS.items():
        path = source / filename
        try:
            data = path.read_bytes()
            valid_svg(data)
        except (OSError, ET.ParseError, ValueError) as error:
            print(f'::warning::Invalid or missing {filename}: {error}; retaining previous embed')
            invalid.append(filename)
            continue
        destination.mkdir(exist_ok=True)
        (destination / filename).write_bytes(data)
        if pattern:
            text = re.sub(pattern, 'profile/' + filename, text)
        elif '<!-- profile-analytics -->' in text:
            text = text.replace('<!-- profile-analytics -->', '![Recent contribution summary](profile/analytics.svg)')
    return text, invalid


def publish():
    text, invalid = publish_cards(README.read_text(), CARD_DIR, ROOT / 'profile')
    refresh_waka_badge(text)
    README.write_text(text)
    if invalid:
        if os.getenv('GITHUB_ENV'):
            with open(os.environ['GITHUB_ENV'], 'a') as env:
                env.write('PROFILE_INVALID=true\n')
        print('::warning::Unavailable cards: ' + ', '.join(invalid))


def image_urls(text):
    urls = set(re.findall(r'<(?:img|source)\b[^>]*?\b(?:src|srcset)="([^"]+)"', text))
    urls.update(re.findall(r'!\[[^\]]*\]\(([^)\s]+)', text))
    return sorted(urls)


def validate_remote(url):
    try:
        data = request(html.unescape(url), authenticated=False)
        try:
            valid_svg(data)
        except ET.ParseError:
            if not data.startswith((b'\x89PNG\r\n\x1a\n', b'GIF87a', b'GIF89a', b'\xff\xd8\xff')) and not (data[:4] == b'RIFF' and data[8:12] == b'WEBP'):
                raise ValueError('Response is not a recognized image')
    except Exception as error:
        return url, str(error)
    return None


def validate(external=False):
    urls = image_urls(README.read_text())
    remote = []
    for url in urls:
        if url.startswith(('https://', 'http://')):
            remote.append(url)
            continue
        path = ROOT / url
        if not path.is_file():
            raise ValueError(f'Missing local image: {url}')
        if path.suffix == '.svg':
            valid_svg(path.read_bytes())
    if external:
        with ThreadPoolExecutor(max_workers=6) as executor:
            failures = [problem for problem in executor.map(validate_remote, remote) if problem]
        for url, error in failures:
            print(f'::error::External image check failed for {url}: {error}')
        if failures:
            raise SystemExit(f'{len(failures)} external image checks failed')
    print(f'Validated {len(urls)} image references (external={external})')


if __name__ == '__main__':
    command = sys.argv[1]
    if command == 'activity':
        activity()
    elif command == 'graph':
        graph()
    elif command == 'publish':
        publish()
    elif command == 'waka':
        refresh_waka_badge(README.read_text())
    elif command == 'validate':
        validate('--external' in sys.argv)
    else:
        raise SystemExit('Unknown command')
