import logging
from typing import Optional

from mcp.server.fastmcp import FastMCP
from apps.reddit.config import CONFIG
from apps.reddit.references.web.api.subreddits import ApiServiceRedditSubreddits
from apps.reddit.references.web.api.users import ApiServiceRedditUsers
from apps.reddit.references.web.api.posts import ApiServiceRedditPosts

logger = logging.getLogger("harqis-mcp.reddit")


def register_reddit_tools(mcp: FastMCP):

    # ── Subreddits ────────────────────────────────────────────────────────

    @mcp.tool()
    def get_reddit_posts(subreddit: str, sort: str = 'hot', limit: int = 25,
                         t: str = None) -> dict:
        """Get posts from a subreddit.

        Args:
            subreddit: Subreddit name without r/ prefix (e.g. 'python', 'worldnews').
            sort:      'hot', 'new', 'top', 'rising', 'controversial'. Default 'hot'.
            limit:     Number of posts to return (1–100). Default 25.
            t:         Time filter for 'top'/'controversial': 'hour','day','week','month','year','all'.

        Returns:
            Listing with data.children list of post objects. Each post has title, author,
            score, num_comments, url, selftext, created_utc, permalink.
        """
        logger.info("Tool called: get_reddit_posts r/%s sort=%s", subreddit, sort)
        result = ApiServiceRedditSubreddits(CONFIG).get_posts(subreddit, sort=sort,
                                                               limit=limit, t=t)
        return result if isinstance(result, dict) else {}

    @mcp.tool()
    def get_reddit_subreddit_info(subreddit: str) -> dict:
        """Get metadata and stats for a subreddit.

        Args:
            subreddit: Subreddit name without r/ prefix.

        Returns:
            t5 object with display_name, title, description, subscribers,
            active_user_count, over18, subreddit_type, created_utc.
        """
        logger.info("Tool called: get_reddit_subreddit_info r/%s", subreddit)
        result = ApiServiceRedditSubreddits(CONFIG).get_info(subreddit)
        return result if isinstance(result, dict) else {}

    @mcp.tool()
    def get_reddit_comments(subreddit: str, article_id: str,
                             sort: str = 'confidence', limit: int = 50) -> list:
        """Get comments for a Reddit post.

        Args:
            subreddit:  Subreddit name.
            article_id: Post ID (base-36, without 't3_' prefix — visible in the URL).
            sort:       'confidence','top','new','controversial','old','qa'. Default 'confidence'.
            limit:      Max comments to return. Default 50.

        Returns:
            List with [0] = post listing, [1] = comment tree listing.
        """
        logger.info("Tool called: get_reddit_comments r/%s/%s", subreddit, article_id)
        result = ApiServiceRedditSubreddits(CONFIG).get_comments(subreddit, article_id,
                                                                  sort=sort, limit=limit)
        return result if isinstance(result, list) else []

    @mcp.tool()
    def search_reddit(query: str, subreddit: str = None, sort: str = 'relevance',
                      t: str = 'all', limit: int = 25) -> dict:
        """Search Reddit posts globally or within a specific subreddit.

        Args:
            query:     Search query string.
            subreddit: Restrict to this subreddit. None = global search.
            sort:      'relevance','hot','top','new','comments'. Default 'relevance'.
            t:         Time filter: 'hour','day','week','month','year','all'. Default 'all'.
            limit:     Max results (1–100). Default 25.

        Returns:
            Listing with matching posts.
        """
        logger.info("Tool called: search_reddit query=%s subreddit=%s", query, subreddit)
        result = ApiServiceRedditSubreddits(CONFIG).search(query, subreddit=subreddit,
                                                            sort=sort, t=t, limit=limit)
        return result if isinstance(result, dict) else {}

    # ── Users ─────────────────────────────────────────────────────────────

    @mcp.tool()
    def get_reddit_me() -> dict:
        """Get the authenticated Reddit user's profile, karma, and inbox status.

        Returns:
            User object with name, total_karma, link_karma, comment_karma,
            has_mail, inbox_count, is_mod, is_gold, verified.
        """
        logger.info("Tool called: get_reddit_me")
        result = ApiServiceRedditUsers(CONFIG).get_me()
        return result if isinstance(result, dict) else {}

    @mcp.tool()
    def get_reddit_user(username: str) -> dict:
        """Get a Reddit user's public profile.

        Args:
            username: Reddit username without u/ prefix.

        Returns:
            t2 object with name, total_karma, link_karma, comment_karma,
            created_utc, is_mod, icon_img.
        """
        logger.info("Tool called: get_reddit_user username=%s", username)
        result = ApiServiceRedditUsers(CONFIG).get_user(username)
        return result if isinstance(result, dict) else {}

    @mcp.tool()
    def get_reddit_inbox(filter: str = 'unread', limit: int = 25) -> dict:
        """Get Reddit inbox messages.

        Args:
            filter: 'inbox' (all), 'unread', 'sent', 'mentions', 'comments'. Default 'unread'.
            limit:  Max messages (1–100). Default 25.

        Returns:
            Listing with message objects containing subject, body, author, created_utc.
        """
        logger.info("Tool called: get_reddit_inbox filter=%s", filter)
        result = ApiServiceRedditUsers(CONFIG).get_inbox(filter=filter, limit=limit)
        return result if isinstance(result, dict) else {}

    # ── Posts / Write ─────────────────────────────────────────────────────

    @mcp.tool()
    def submit_reddit_post(subreddit: str, title: str, text: str) -> dict:
        """Submit a text post to a subreddit.

        Args:
            subreddit: Target subreddit without r/ prefix.
            title:     Post title (max 300 chars).
            text:      Post body in markdown.

        Returns:
            Dict with json.data containing url, id, name of the new post.
        """
        logger.info("Tool called: submit_reddit_post r/%s title=%s", subreddit, title)
        result = ApiServiceRedditPosts(CONFIG).submit_post(subreddit, title, text=text)
        return result if isinstance(result, dict) else {}

    @mcp.tool()
    def submit_reddit_comment(parent_fullname: str, text: str) -> dict:
        """Reply to a Reddit post or comment.

        Args:
            parent_fullname: Fullname of the parent — 't3_xxx' for a post, 't1_xxx' for a comment.
                             The fullname is the 'name' field in any Reddit API response.
            text:            Reply body in markdown.

        Returns:
            Dict with the new comment data.
        """
        logger.info("Tool called: submit_reddit_comment parent=%s", parent_fullname)
        result = ApiServiceRedditPosts(CONFIG).submit_comment(parent_fullname, text)
        return result if isinstance(result, dict) else {}

    @mcp.tool()
    def vote_reddit(fullname: str, direction: int) -> dict:
        """Vote on a Reddit post or comment.

        Args:
            fullname:  Fullname of the post (t3_xxx) or comment (t1_xxx) to vote on.
            direction: 1 = upvote, -1 = downvote, 0 = remove vote.
        """
        logger.info("Tool called: vote_reddit fullname=%s dir=%d", fullname, direction)
        result = ApiServiceRedditPosts(CONFIG).vote(fullname, direction)
        return result if isinstance(result, dict) else {}
