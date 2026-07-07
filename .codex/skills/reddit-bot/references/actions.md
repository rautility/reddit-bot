# Action Reference (offline fallback)

Prefer the live command — it also shows current defaults and quota:

```bash
.venv/bin/python scripts/reddit_tool.py capabilities
```

This file mirrors that schema for when you cannot run it. Fields are the columns
of the action file; `do` accepts each as a `--flag`.

| action | required | optional | link is |
|--------|----------|----------|---------|
| upvote | link | — | canonical post URL |
| downvote | link | — | canonical post URL |
| comment | link, comment | — | canonical post URL |
| save | link | — | canonical post URL |
| hide | link | — | canonical post URL |
| join | link | — | community URL |
| leave | link | — | community URL |
| follow | link | — | user URL |
| unfollow | link | — | user URL |
| update_bio | body | — | (ignored; body = new bio) |
| dm | recipient, message | title (subject) | (ignored) |
| post_text | title, subreddit | body (text), flair | (ignored) |
| post_link | title, subreddit, body (URL) | flair | (ignored) |
| post_image | title, subreddit, body (image path) | flair | (ignored) |
| crosspost | link, subreddit (dest) | title | source post URL |
| human_search | link (= query text) | subreddit | search query |
| search_upvote | link (= query text) | subreddit | search query |

## Field glossary

- **link** — target Reddit URL; for post actions a canonical `/comments/` URL.
- **comment** — comment body text.
- **title** — post title, or DM subject.
- **subreddit** — destination community name or URL for post/crosspost.
- **body** — overloaded: post text, or URL (`post_link`), or image path
  (`post_image`), or new bio (`update_bio`).
- **flair** — optional post flair.
- **recipient** — username for a `dm`.
- **message** — message body for a `dm`.

## Examples

```bash
TOOL=".venv/bin/python scripts/reddit_tool.py"

$TOOL do --action downvote --link "https://www.reddit.com/r/excel/comments/1ropoew/x/"
$TOOL do --action comment  --link "<post_url>" --comment "Great point."
$TOOL do --action join     --link "https://www.reddit.com/r/excel/"
$TOOL do --action dm       --recipient "u/someone" --title "Hi" --message "..."
$TOOL do --action post_text --subreddit "test" --title "Hello" --body "Body text."
$TOOL do --action post_link --subreddit "test" --title "Cool" --body "https://example.com"
$TOOL do --action crosspost --link "<source_post_url>" --subreddit "test"
$TOOL do --action human_search --query "best excel formulas"
$TOOL search-upvote --query "best excel formulas"
$TOOL schedule add --action search_upvote --query "best excel formulas" --at 2026-07-06T09:00:00
$TOOL external-search-upvote --query "best excel formulas" --json
$TOOL queue recover-stale
$TOOL queue retry --id 123
$TOOL queue retry --all --account "Particular-Arm2102"
```

## URL contract

Post actions require `https://www.reddit.com/r/<subreddit>/comments/<post_id>/<slug>/`.
Share shortlinks (`/r/<sub>/s/<id>`) are rejected at submit time; resolve them to
the canonical `/comments/` URL first (open the share link in the saved profile and
copy the resulting address).
