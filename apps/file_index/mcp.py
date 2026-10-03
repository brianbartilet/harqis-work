"""CLI-first catalog adapter; public sharing stays behind explicit UI publication."""
import logging
from mcp.server.fastmcp import FastMCP
from apps.file_index.references.web.api.catalog import ApiServiceFileIndex

logger = logging.getLogger('harqis-mcp.file_index')


def register_file_index_tools(mcp: FastMCP):
    @mcp.tool()
    def search_file_index_files(query: str = '', category: str = '', offset: int = 0, limit: int = 50) -> dict:
        """Search indexed file metadata on the catalog host.

        Args:
            query: Name or tag search text.
            category: Optional canonical category ID.
            offset: Zero-based pagination offset.
            limit: Page size, 1–200.
        """
        logger.info('Tool called: search_file_index_files')
        result = ApiServiceFileIndex().search_files(query, category, offset, limit)
        logger.info('search_file_index_files done')
        return result

    @mcp.tool()
    def get_file_index_file(file_id: str) -> dict:
        """Read metadata and storage locations for one file.

        Args:
            file_id: Catalog file ID.
        """
        logger.info('Tool called: get_file_index_file')
        result = ApiServiceFileIndex().get_file(file_id)
        logger.info('get_file_index_file done')
        return result

    @mcp.tool()
    def list_file_index_sources() -> dict:
        """List configured discovery roots and their last scan status."""
        logger.info('Tool called: list_file_index_sources')
        result = ApiServiceFileIndex().list_sources()
        logger.info('list_file_index_sources done')
        return result

    @mcp.tool()
    def get_file_index_package(package_id: str) -> dict:
        """Read owner-visible package revisions and audit history.

        Args:
            package_id: Catalog package ID.
        """
        logger.info('Tool called: get_file_index_package')
        result = ApiServiceFileIndex().get_package(package_id)
        logger.info('get_file_index_package done')
        return result

    @mcp.tool()
    def create_file_index_output(path: str, provenance: dict | None = None) -> dict:
        """Write generated-output metadata for a file inside an enabled source root.

        Args:
            path: Generated local file path on the catalog host.
            provenance: Optional producer/task identifiers; do not include secrets.
        """
        logger.info('Tool called: create_file_index_output')
        result = ApiServiceFileIndex().register_output(path, provenance or {})
        logger.info('create_file_index_output done')
        return result
