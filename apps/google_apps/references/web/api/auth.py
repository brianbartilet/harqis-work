from apps.google_apps.references.web.base_api_service import BaseApiServiceGoogle


class ApiServiceGoogleAuth(BaseApiServiceGoogle):

    def __init__(self, source_id):
        super(ApiServiceGoogleAuth, self).__init__(source_id)
        self.initialize()

    def initialize(self):
        ...



