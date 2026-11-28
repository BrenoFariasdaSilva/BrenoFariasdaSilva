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


def refresh_waka_badge(text):
    section = re.search(r'<!--START_SECTION:waka-->([\s\S]*?)<!--END_SECTION:waka-->', text)
    total = re.search(r'^Total Time: (.+)$', section[1], re.M) if section else None
    if not total:
        return
    value = html.escape(total[1])
    badge = f'<svg xmlns="http://www.w3.org/2000/svg" width="280" height="20" role="img" aria-label="WakaTime: {value}"><title>WakaTime: {value}</title><rect width="280" height="20" rx="3" fill="#555"/><rect x="76" width="204" height="20" rx="3" fill="#1683a3"/><g fill="white" font-family="Verdana,Arial,sans-serif" font-size="11" text-anchor="middle"><text x="38" y="14">WakaTime</text><text x="178" y="14">{value}</text></g></svg>\n'
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
