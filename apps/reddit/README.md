# Reddit Integration (`apps/reddit`)

Reddit OAuth2 integration using the [Reddit API](https://www.reddit.com/dev/api/).

Supports reading subreddits, user profiles, inbox, and write operations (posts, comments, votes).

---

## Setup

### 1. Reddit Account Requirements

Before you can create an app, your Reddit account must meet these criteria:

- **Verified email** — go to [https://www.reddit.com/settings](https://www.reddit.com/settings) and verify your email address
- **Account age** — accounts must be at least a few days to a few weeks old
- **Sufficient karma** — some accounts need a minimum karma threshold
- **Policy compliance** — review the [Responsible Builder Policy](https://support.reddithelp.com/hc/en-us/articles/42728983564564-Responsible-Builder-Policy) before creating an app

If you see a policy error when visiting [https://www.reddit.com/prefs/apps](https://www.reddit.com/prefs/apps), your account likely doesn't meet one of the above criteria yet.

### 2. Create a Reddit App

1. Go to [https://www.reddit.com/prefs/apps](https://www.reddit.com/prefs/apps)
2. Click **"create another app..."**
3. Select **"script"** (for personal use / automation)
4. Fill in a name and set redirect URI to `http://localhost` (not used for script apps)
5. Copy the **client ID** (shown under the app name) and **client secret**

### 3. Environment Variables

Add to `.env/apps.env`:

```env
# REDDIT
REDDIT_CLIENT_ID=your_app_client_id
REDDIT_CLIENT_SECRET=your_app_client_secret
REDDIT_USERNAME=your_reddit_username
REDDIT_PASSWORD=your_reddit_password
REDDIT_USER_AGENT=harqis-work:v1.0 (by /u/your_reddit_username)
REDDIT_DEFAULT_SUBREDDIT=python
```

`REDDIT_USER_AGENT` must follow Reddit's required format: `<platform>:<app_id>:<version> (by /u/<username>)`.

### 4. Config (`apps_config.yaml`)

```yaml
REDDIT:
  app_id: 'reddit'
  client: 'rest'
  parameters:
    base_url: 'https://oauth.reddit.com/'
    response_encoding: 'utf-8'
    verify: True
    timeout: 30
    stream: False
  app_data:
    client_id: ${REDDIT_CLIENT_ID}
    client_secret: ${REDDIT_CLIENT_SECRET}
    username: ${REDDIT_USERNAME}
    password: ${REDDIT_PASSWORD}
    user_agent: ${REDDIT_USER_AGENT}
    default_subreddit: ${REDDIT_DEFAULT_SUBREDDIT}
```

---

## Authentication

Uses **OAuth2 password grant** (`grant_type=password`). The base service fetches an access token at initialization time via `https://www.reddit.com/api/v1/access_token`.

GET requests use the harqis-core request builder with `Authorization: bearer <token>`.
POST/write requests use a direct `requests.Session` (Reddit write API requires `application/x-www-form-urlencoded`).

---

## API Services

### `ApiServiceRedditSubreddits`

| Method | Description |
|--------|-------------|
| `get_posts(subreddit, sort, limit, t)` | Get posts from a subreddit (hot/new/top/rising/controversial) |
| `get_info(subreddit)` | Get subreddit metadata and stats |
| `get_comments(subreddit, article_id, sort, limit)` | Get comment tree for a post |
| `search(query, subreddit, sort, t, limit)` | Search posts globally or within a subreddit |
| `get_subscribed(limit, after)` | List subreddits the authenticated user is subscribed to |

### `ApiServiceRedditUsers`

| Method | Description |
|--------|-------------|
| `get_me()` | Authenticated user's profile + karma |
| `get_karma()` | Karma breakdown by subreddit |
| `get_user(username)` | Any user's public profile |
| `get_submitted(username, ...)` | User's submitted posts |
| `get_comments_history(username, ...)` | User's comment history |
| `get_saved(username, ...)` | User's saved posts/comments |
| `get_inbox(filter, limit, after)` | Inbox messages (all/unread/sent/mentions) |
| `send_message(to, subject, text)` | Send a private message |
| `mark_read(*fullnames)` | Mark messages as read |

### `ApiServiceRedditPosts`

| Method | Description |
|--------|-------------|
| `submit_post(subreddit, title, text, url, ...)` | Submit a text or link post |
| `submit_comment(parent_fullname, text)` | Reply to a post (`t3_xxx`) or comment (`t1_xxx`) |
| `vote(fullname, direction)` | Upvote (1), downvote (-1), or remove vote (0) |
| `save(fullname, category)` | Save a post or comment |
| `unsave(fullname)` | Unsave a post or comment |
| `delete(fullname)` | Delete your own post or comment |
| `edit(fullname, text)` | Edit the text of your own post or comment |
| `subscribe(subreddit_name, action)` | Subscribe or unsubscribe from a subreddit |

---

## Tests

```sh
# Run all Reddit tests
pytest apps/reddit/tests/ -v

# Smoke tests only (auth + connectivity)
pytest apps/reddit/tests/ -m smoke -v

# Sanity tests
pytest apps/reddit/tests/ -m sanity -v
```

Tests are live integration tests — requires valid credentials in `.env/apps.env`.

---

## MCP Tools

| Tool | Description |
|------|-------------|
| `get_reddit_posts` | Get posts from a subreddit |
| `get_reddit_subreddit_info` | Get subreddit metadata and stats |
| `get_reddit_comments` | Get comment tree for a post |
| `search_reddit` | Search posts globally or within a subreddit |
| `get_reddit_me` | Get authenticated user's profile |
| `get_reddit_user` | Get any user's public profile |
| `get_reddit_inbox` | Get inbox messages |
| `submit_reddit_post` | Submit a text post to a subreddit |
| `submit_reddit_comment` | Reply to a post or comment |
| `vote_reddit` | Upvote, downvote, or remove vote |

---

## Notes

- Reddit rate limits: 60 requests/minute for OAuth clients. No retry logic is built in.
- Fullnames use prefixes: `t1_` (comment), `t2_` (account), `t3_` (post), `t4_` (message), `t5_` (subreddit).
- The `article_id` for `get_reddit_comments` is the base-36 post ID visible in the URL (without `t3_`).
- Write operations (`submit_post`, `submit_comment`, `vote`) require the app to have the appropriate OAuth scopes (`submit`, `vote`, `privatemessages`). For password-grant scripts, all scopes are granted by default.
