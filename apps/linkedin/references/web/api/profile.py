from apps.linkedin.references.web.base_api_service import BaseApiServiceLinkedIn
from core.web.services.core.decorators.deserializer import deserialized


class ApiServiceLinkedInProfile(BaseApiServiceLinkedIn):
    """
    LinkedIn API — member profile and email.

    Requires scopes: r_liteprofile, email

    Methods:
        get_me()            → Authenticated member's lite profile (id, name, photo)
        get_email()         → Authenticated member's primary email address
        get_profile(id)     → Any member's public lite profile by person ID
    """

    def __init__(self, config, **kwargs):
        super(ApiServiceLinkedInProfile, self).__init__(config, **kwargs)

    @deserialized(dict)
    def get_me(self):
        """
        Get the authenticated member's profile via OpenID Connect userinfo endpoint.

        Requires 'openid profile' scopes.

        Returns:
            Dict with sub (person ID), name, given_name, family_name, picture, email.
        """
        self.request.get() \
            .add_uri_parameter('userinfo')
        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def get_email(self):
        """
        Get the authenticated member's profile including email via OpenID Connect.

        Requires 'openid profile email' scopes.

        Returns:
            Dict with sub, name, given_name, family_name, picture, email.
        """
        self.request.get() \
            .add_uri_parameter('userinfo')
        return self.client.execute_request(self.request.build())

    @deserialized(dict)
    def get_profile(self, person_id: str):
        """
        Get a member's public profile by their person ID.

        Args:
            person_id: LinkedIn member ID (the 'sub' field from /v2/userinfo).

        Returns:
            Dict with id, localizedFirstName, localizedLastName, profilePicture.
        """
        self.request.get() \
            .add_uri_parameter('people') \
            .add_uri_parameter(f'id={person_id}') \
            .add_query_string('projection', '(id,localizedFirstName,localizedLastName,profilePicture)')
        return self.client.execute_request(self.request.build())
