"""Local catalog facade: no remote REST base class or credentials required."""
from apps.file_index.store import Store


class ApiServiceFileIndex:
    def __init__(self, store=None):
        self.store = store or Store()

    def search_files(self, query='', category='', offset=0, limit=50):
        if not 1 <= limit <= 200 or offset < 0:
            raise ValueError('limit must be 1–200 and offset nonnegative')
        return self.store.catalog(query, category, offset=offset, limit=limit)

    def get_file(self, file_id):
        return {**self.store.get('files', file_id), 'locations': self.store.locations(file_id)}

    def list_sources(self):
        return {'items': self.store.all('sources')}

    def get_package(self, package_id):
        return {**self.store.get('packages', package_id),
                'revisions': [r for r in self.store.all('revisions') if r['package_id'] == package_id],
                'history': self.store.history(package_id)}

    def register_output(self, path, provenance):
        from apps.file_index.service import register_output
        return {'item': register_output(path, provenance, self.store)}
