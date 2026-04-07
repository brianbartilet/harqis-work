from typing import Optional

from apps.linkedin.references.web.base_api_service import BaseApiServiceLinkedIn
from core.web.services.core.decorators.deserializer import deserialized


class ApiServiceLinkedInPosts(BaseApiServiceLinkedIn):
    """
    LinkedIn API — UGC posts (create, read, delete).

    Requires scope: w_member_social

    The authenticated member's person URN is read from config.app_data['person_id']
    and formatted as 'urn:li:person:{person_id}' for post authorship.

    Methods:
        create_post()       → Publish a text or article post
        get_post()          → Retrieve a post by URN
        delete_post()       → Delete your own post
    """

    def __init__(self, config, **kwargs):
        super(ApiServiceLinkedInPosts, self).__init__(config, **kwargs)
        person_id = config.app_data.get('person_id', '')
        self._author_urn = f'urn:li:person:{person_id}'

    @deserialized(dict)
    def create_post(self, text: str, visibility: str = 'PUBLIC',
                    article_url: str = None, article_title: str = None,
                    article_description: str = None) -> dict:
        """
        Publish a text or article post on behalf of the authenticated member.

        Requires 'w_member_social' scope.

        Args:
            text:                Post body / share commentary (markdown supported).
            visibility:          'PUBLIC' or 'CONNECTIONS'. Default 'PUBLIC'.
            article_url:         URL to share as an article (sets shareMediaCategory to ARTICLE).
            article_title:       Optional title for the shared article.
            article_description: Optional description for the shared article.

        Returns:
            Empty dict on success (HTTP 201). The created post's URN is returned
            in the 'X-RestLi-Id' response header — not captured here.
        """
        media_category = 'NONE'
        media = []
        if article_url:
            media_category = 'ARTICLE'
            media_item = {'status': 'READY', 'originalUrl': article_url}
            if article_title:
                media_item['title'] = {'text': article_title}
            if article_description:
                media_item['description'] = {'text': article_description}
            media.append(media_item)

        payload = {
            'author': self._author_urn,
            'lifecycleState': 'PUBLISHED',
            'specificContent': {
                'com.linkedin.ugc.ShareContent': {
                    'shareCommentary': {'text': text},
                    'shareMediaCategory': media_category,
                }
            },
            'visibility': {
                'com.linkedin.ugc.MemberNetworkVisibility': visibility,
            },
        }
        if media:
            payload['specificContent']['com.linkedin.ugc.ShareContent']['media'] = media

        self.request.post() \
            .add_uri_parameter('ugcPosts') \
            .add_json_payload(payload)
        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def get_post(self, post_urn: str) -> dict:
        """
        Retrieve a UGC post by its URN.

        Args:
            post_urn: Full post URN (e.g. 'urn:li:ugcPost:1234567890').
                      Colons are URL-encoded automatically.

        Returns:
            Post object with author, lifecycleState, specificContent, visibility.
        """
        encoded_urn = post_urn.replace(':', '%3A')
        self.request.get() \
            .add_uri_parameter('ugcPosts') \
            .add_uri_parameter(encoded_urn)
        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def delete_post(self, post_urn: str) -> dict:
        """
        Delete your own UGC post.

        Args:
            post_urn: Full post URN (e.g. 'urn:li:ugcPost:1234567890').

        Returns:
            Empty dict on success (HTTP 204).
        """
        encoded_urn = post_urn.replace(':', '%3A')
        self.request.delete() \
            .add_uri_parameter('ugcPosts') \
            .add_uri_parameter(encoded_urn)
        return self.client.execute_request(self.request.build())
