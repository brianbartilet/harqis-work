import logging

from mcp.server.fastmcp import FastMCP
from apps.linkedin.config import CONFIG
from apps.linkedin.references.web.api.profile import ApiServiceLinkedInProfile
from apps.linkedin.references.web.api.posts import ApiServiceLinkedInPosts

logger = logging.getLogger("harqis-mcp.linkedin")


def register_linkedin_tools(mcp: FastMCP):

    # ── Profile ───────────────────────────────────────────────────────────

    @mcp.tool()
    def get_linkedin_me() -> dict:
        """Get the authenticated LinkedIn member's lite profile.

        Returns:
            Dict with id, localizedFirstName, localizedLastName, profilePicture.
        """
        logger.info("Tool called: get_linkedin_me")
        result = ApiServiceLinkedInProfile(CONFIG).get_me()
        return result if isinstance(result, dict) else {}

    @mcp.tool()
    def get_linkedin_email() -> dict:
        """Get the authenticated LinkedIn member's primary email address.

        Returns:
            Dict with elements list. Each element contains handle~ with emailAddress.
        """
        logger.info("Tool called: get_linkedin_email")
        result = ApiServiceLinkedInProfile(CONFIG).get_email()
        return result if isinstance(result, dict) else {}

    @mcp.tool()
    def get_linkedin_profile(person_id: str) -> dict:
        """Get a LinkedIn member's public lite profile by their person ID.

        Args:
            person_id: LinkedIn member ID (numeric string from a /v2/me response,
                       without the 'urn:li:person:' prefix).

        Returns:
            Dict with id, localizedFirstName, localizedLastName, profilePicture.
        """
        logger.info("Tool called: get_linkedin_profile person_id=%s", person_id)
        result = ApiServiceLinkedInProfile(CONFIG).get_profile(person_id)
        return result if isinstance(result, dict) else {}

    # ── Posts ─────────────────────────────────────────────────────────────

    @mcp.tool()
    def create_linkedin_post(text: str, visibility: str = 'PUBLIC',
                             article_url: str = None, article_title: str = None,
                             article_description: str = None) -> dict:
        """Publish a post on LinkedIn on behalf of the authenticated member.

        Args:
            text:                Post body / share commentary.
            visibility:          'PUBLIC' or 'CONNECTIONS'. Default 'PUBLIC'.
            article_url:         Optional URL to share as an article link.
            article_title:       Optional title for the article.
            article_description: Optional description for the article.

        Returns:
            Empty dict on success (HTTP 201). LinkedIn returns the new post URN
            in the X-RestLi-Id response header (not captured here).
        """
        logger.info("Tool called: create_linkedin_post visibility=%s", visibility)
        result = ApiServiceLinkedInPosts(CONFIG).create_post(
            text=text,
            visibility=visibility,
            article_url=article_url,
            article_title=article_title,
            article_description=article_description,
        )
        return result if isinstance(result, dict) else {}

    @mcp.tool()
    def get_linkedin_post(post_urn: str) -> dict:
        """Retrieve a LinkedIn UGC post by its URN.

        Args:
            post_urn: Full post URN (e.g. 'urn:li:ugcPost:1234567890').

        Returns:
            Post object with author, lifecycleState, specificContent, visibility.
        """
        logger.info("Tool called: get_linkedin_post urn=%s", post_urn)
        result = ApiServiceLinkedInPosts(CONFIG).get_post(post_urn)
        return result if isinstance(result, dict) else {}

    @mcp.tool()
    def delete_linkedin_post(post_urn: str) -> dict:
        """Delete your own LinkedIn post.

        Args:
            post_urn: Full post URN (e.g. 'urn:li:ugcPost:1234567890').

        Returns:
            Empty dict on success (HTTP 204).
        """
        logger.info("Tool called: delete_linkedin_post urn=%s", post_urn)
        result = ApiServiceLinkedInPosts(CONFIG).delete_post(post_urn)
        return result if isinstance(result, dict) else {}
