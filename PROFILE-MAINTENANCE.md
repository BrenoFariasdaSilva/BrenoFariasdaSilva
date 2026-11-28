# Profile maintenance

## How the profile works

- The statistics workflow generates GitHub Stats, Top Languages, Streak, Trophies, a 30-day contribution graph, and a 30-day contribution summary. Each successful SVG is validated before being committed; the README switches to that local SVG only when it exists. Failed cards retain their existing embed or the last known good image; the run reports failure. The initial external stats/streak/trophy/graph embeds remain until the first successful generation of each card.
- `PROFILE_STATS_TOKEN` is optional. The default repository token may have limited visibility. For broader statistics, create a suitably scoped read-only token and store it as an Actions secret named `PROFILE_STATS_TOKEN`. Only grant access to private repositories if you want their aggregate contribution metrics to be published publicly. The token is never written to a file. The recent activity script requests public events only and excludes this profile repository to avoid automation noise. Top Languages measures repository code composition, not experience or coding time.
- The contribution graph and summary use the GitHub contribution calendar (not commit counts). Repobeats was replaced with a clearly labeled account-wide contribution summary and a link to GitHub Contribution Analytics; this is not a direct import of that project's metrics.
- WakaTime continues to use the owner's pinned action fork. Its reported total includes masked/Other time; the table shows selected rows, and the header badge reflects the all-time total. Existing WakaTime credentials are reused.
- Spotify Recently Played uses the upstream Cloudflare endpoint. Reconnect at <https://spotify-recently-played.jeffreyca.workers.dev/> if authorization expires. Now Playing authorization is managed at <https://spotify-github-profile.kittinanx.com/>. LeetCode and the remaining external badges may also experience external outages.
- The snake's light and dark images remain on `output`. Other generated statistics and badge assets live on `main`. Snake publishing keeps history and does not modify the `main` branch.
- README writers share a concurrency group. GitHub may replace an older pending run with a newer one; scheduled and manually triggered runs are available. Do not run simultaneous manual updates if you want every requested run to execute.
- Brand assets are stored in `badges/`; Matplotlib is intentionally text-only. The link destinations and spoken-language flags are retained as provided; verify the LinkedIn and WhatsApp account details if needed.

## Initial setup

Run these from your authenticated GitHub CLI session after pushing the patches. Run the workflows sequentially (wait for each to finish before starting the next):

```sh
gh workflow run waka-readme.yml --ref main
gh workflow run update-gh-activity.yml --ref main
gh workflow run profile-stats.yml --ref main
gh workflow run main.yml --ref main
gh workflow run validate-profile.yml --ref main
```

Check Actions with `gh run list` and `gh run view RUN_ID --log-failed`. A stats-generation failure can indicate insufficient token scope, dependency availability or upstream API rate limits; the original/last-good image is intentionally retained. The validator checks external images on manual/scheduled runs, and local assets on every relevant push or PR.

## Local checks

```sh
python3 -m unittest discover -s tests -v
python3 scripts/profile.py validate
# Requires network access to external image providers:
python3 scripts/profile.py validate --external
```
