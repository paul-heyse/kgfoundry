"""Overview of harvester.

This module bundles harvester logic for the kgfoundry stack. It groups related helpers so downstream
packages can import a single cohesive namespace. Refer to the functions and classes below for
implementation specifics.
"""

# [nav:section public-api]

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import requests

from kgfoundry_common.errors import DownloadError, UnsupportedMIMEError
from kgfoundry_common.models import Doc
from kgfoundry_common.navmap_loader import load_nav_metadata

__all__ = [
    "OpenAccessHarvester",
]
__navmap__ = load_nav_metadata(__name__, tuple(__all__))


HTTP_OK = 200


@dataclass(frozen=True)
class HarvesterConfig:
    """Configuration for OpenAccessHarvester.

    Provides configuration options for customizing API endpoints and output
    directory for the harvester. All fields have sensible defaults.

    Attributes
    ----------
    openalex_base : str
        Base URL for the OpenAlex API. Defaults to "https://api.openalex.org".
    unpaywall_base : str
        Base URL for the Unpaywall API. Defaults to "https://api.unpaywall.org".
    pdf_host_base : str | None
        Optional base URL for a custom PDF hosting service. If provided,
        PDFs will be resolved using this host. Defaults to None.
    out_dir : str
        Output directory path where downloaded PDFs will be saved.
        Defaults to "/data/pdfs".
    """

    openalex_base: str = "https://api.openalex.org"
    unpaywall_base: str = "https://api.unpaywall.org"
    pdf_host_base: str | None = None
    out_dir: str = "/data/pdfs"


# [nav:anchor OpenAccessHarvester]
class OpenAccessHarvester:
    """Harvester for downloading open-access PDFs from OpenAlex.

    Provides functionality to search for academic works in OpenAlex, resolve
    PDF URLs through multiple sources (direct links, locations, Unpaywall, or
    custom PDF host), and download PDFs to local storage.

    Sets up HTTP session with proper headers and creates output directory
    if it doesn't exist.

    Parameters
    ----------
    user_agent : str
        User agent string for HTTP requests (required by OpenAlex API).
    contact_email : str
        Contact email address for API requests (required by OpenAlex API).
    config : HarvesterConfig | None, optional
        Optional configuration object. If None, uses default HarvesterConfig.
        Defaults to None.
    """

    def __init__(
        self,
        user_agent: str,
        contact_email: str,
        config: HarvesterConfig | None = None,
    ) -> None:
        cfg = config or HarvesterConfig()
        self.ua = user_agent
        self.email = contact_email
        self.openalex = cfg.openalex_base.rstrip("/")
        self.unpaywall = cfg.unpaywall_base.rstrip("/")
        self.pdf_host = (cfg.pdf_host_base or "").rstrip("/")
        self.out_dir = cfg.out_dir
        Path(self.out_dir).mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": f"{self.ua} ({self.email})"})

    def search(self, topic: str, years: str, max_works: int) -> list[dict[str, object]]:
        """Search for works in OpenAlex matching the topic and year filter.

        Queries the OpenAlex API for works matching the specified topic and
        optional year filter. Returns up to max_works results as a list of
        work dictionaries.

        Parameters
        ----------
        topic : str
            Topic query string (e.g., "machine learning").
        years : str
            Optional year filter string (e.g., "publication_year:2020-2023").
            Empty string means no year filter.
        max_works : int
            Maximum number of works to return (capped at 200 per request).

        Returns
        -------
        list[dict[str, object]]
            List of work dictionaries from OpenAlex API. Each dictionary
            contains work metadata (id, title, doi, locations, etc.).

        Raises
        ------
        TypeError
            If the response payload is not a mapping or contains invalid structure.
        """
        url = f"{self.openalex}/works"
        params: dict[str, str | int] = {
            "topic": topic,
            "per_page": min(200, max_works),
            "cursor": "*",
        }
        if years:
            params["filter"] = years
        response = self.session.get(url, params=params, timeout=30)
        response.raise_for_status()
        raw_payload: object = response.json()
        if not isinstance(raw_payload, Mapping):
            message = "OpenAlex response payload must be a mapping"
            raise TypeError(message)
        if not all(isinstance(key, str) for key in raw_payload):
            message = "OpenAlex payload keys must be strings"
            raise TypeError(message)
        payload = cast("Mapping[str, object]", raw_payload)
        results_obj = payload.get("results", [])
        if not isinstance(results_obj, list):
            message = "OpenAlex response must contain a list of results"
            raise TypeError(message)
        typed_results: list[dict[str, object]] = []
        for entry in results_obj:
            if not isinstance(entry, Mapping):
                continue
            if any(not isinstance(key, str) for key in entry):
                continue
            mapping_entry = cast("Mapping[str, object]", entry)
            typed_results.append(dict(mapping_entry))
        return typed_results[:max_works]

    def resolve_pdf(self, work: Mapping[str, object]) -> str | None:
        """Resolve PDF URL for a work using multiple fallback strategies.

        Attempts to find a PDF URL for the work by trying multiple sources:
        1. Direct PDF URL from best_oa_location
        2. PDF URL from locations array
        3. Unpaywall API lookup (if DOI available)
        4. Custom PDF host URL (if configured and DOI available)

        Parameters
        ----------
        work : Mapping[str, object]
            Work dictionary from OpenAlex API containing work metadata.

        Returns
        -------
        str | None
            PDF URL if found, None otherwise.
        """
        direct = self._lookup_direct_pdf(work)
        if direct:
            return direct

        from_locations = self._lookup_locations_pdf(work.get("locations"))
        if from_locations:
            return from_locations

        doi_obj = work.get("doi")
        if isinstance(doi_obj, str) and doi_obj:
            unpaywall_url = self._resolve_unpaywall_pdf(doi_obj)
            if unpaywall_url:
                return unpaywall_url
            host_url = self._host_pdf_url(doi_obj)
            if host_url:
                return host_url
        return None

    @staticmethod
    def _lookup_direct_pdf(work: Mapping[str, object]) -> str | None:
        """Look up PDF URL from work's best_oa_location field.

        Checks the best_oa_location field in the work dictionary for a
        direct PDF URL.

        Parameters
        ----------
        work : Mapping[str, object]
            Work dictionary from OpenAlex API.

        Returns
        -------
        str | None
            PDF URL from best_oa_location if found, None otherwise.
        """
        best = work.get("best_oa_location")
        if isinstance(best, Mapping):
            pdf_url = best.get("pdf_url")
            if isinstance(pdf_url, str) and pdf_url:
                return pdf_url
        return None

    @staticmethod
    def _lookup_locations_pdf(locations: object) -> str | None:
        """Look up PDF URL from work's locations array.

        Searches through the locations array for the first location with
        a valid PDF URL.

        Parameters
        ----------
        locations : object
            Locations array from work dictionary. Can be a sequence of
            location dictionaries or other types.

        Returns
        -------
        str | None
            PDF URL from locations array if found, None otherwise.
        """
        if isinstance(locations, (str, bytes)):
            return None
        if not isinstance(locations, Sequence):
            return None
        for location in locations:
            if isinstance(location, Mapping):
                candidate = location.get("pdf_url")
                if isinstance(candidate, str) and candidate:
                    return candidate
        return None

    def _resolve_unpaywall_pdf(self, doi: str) -> str | None:
        """Resolve PDF URL using Unpaywall API.

        Queries the Unpaywall API for the given DOI and returns the PDF URL
        from the best open-access location if available.

        Parameters
        ----------
        doi : str
            Digital Object Identifier (DOI) of the work.

        Returns
        -------
        str | None
            PDF URL from Unpaywall if found, None otherwise.
        """
        response = self.session.get(
            f"{self.unpaywall}/v2/{doi}", params={"email": self.email}, timeout=15
        )
        if not response.ok:
            return None
        raw_payload: object = response.json()
        if isinstance(raw_payload, Mapping):
            payload = cast("Mapping[str, object]", raw_payload)
            best_location = payload.get("best_oa_location")
            if isinstance(best_location, Mapping):
                url = best_location.get("url_for_pdf")
                if isinstance(url, str) and url:
                    return url
        return None

    def _host_pdf_url(self, doi: str) -> str | None:
        """Construct PDF URL from custom PDF host configuration.

        Generates a PDF URL using the configured pdf_host_base and the DOI.
        The DOI is sanitized by replacing slashes with underscores.

        Parameters
        ----------
        doi : str
            Digital Object Identifier (DOI) of the work.

        Returns
        -------
        str | None
            PDF URL from custom host if pdf_host_base is configured,
            None otherwise.
        """
        if not self.pdf_host:
            return None
        return f"{self.pdf_host}/pdf/{doi.replace('/', '_')}.pdf"

    def download_pdf(self, url: str, target_path: str | Path) -> Path:
        """Download a PDF file from URL to local path.

        Downloads the PDF file from the given URL and saves it to the
        specified target path. Validates that the response is a PDF-like
        content type.

        Parameters
        ----------
        url : str
            URL of the PDF file to download.
        target_path : str | Path
            Local file path where the PDF will be saved.

        Returns
        -------
        Path
            Path object pointing to the downloaded file.

        Raises
        ------
        DownloadError
            If the HTTP request returns a non-200 status code.
        UnsupportedMIMEError
            If the response content type is not PDF-like.
        """
        response = self.session.get(url, timeout=60)
        if response.status_code != HTTP_OK:
            message = f"Bad status {response.status_code} for {url}"
            raise DownloadError(message)
        content_type = response.headers.get("Content-Type", "application/pdf")
        if not content_type.startswith("application/"):
            message = f"Not a PDF-like content type: {content_type}"
            raise UnsupportedMIMEError(message)
        path_obj = Path(target_path)
        with path_obj.open("wb") as file_handle:
            file_handle.write(response.content)
        return path_obj

    def run(self, topic: str, years: str, max_works: int) -> list[Doc]:
        """Run the complete harvesting workflow.

        Searches for works, resolves PDF URLs, downloads PDFs, and creates
        Doc objects for each successfully downloaded document.

        Parameters
        ----------
        topic : str
            Topic query string (e.g., "machine learning").
        years : str
            Optional year filter string (e.g., "publication_year:2020-2023").
            Empty string means no year filter.
        max_works : int
            Maximum number of works to process.

        Returns
        -------
        list[Doc]
            List of Doc objects for successfully downloaded PDFs.
        """
        docs: list[Doc] = []
        works = self.search(topic, years, max_works)
        for work in works:
            pdf_url = self.resolve_pdf(work)
            if not pdf_url:
                continue
            raw_name = work.get("doi") or work.get("id") or str(int(time.time() * 1000))
            filename = f"{str(raw_name).replace('/', '_')}.pdf"
            destination = Path(self.out_dir) / filename
            destination = self.download_pdf(pdf_url, destination)
            doc = Doc(
                id=f"urn:doc:source:openalex:{work.get('id', 'unknown')}",
                openalex_id=work.get("id"),
                doi=work.get("doi"),
                title=work.get("title", ""),
                authors=[],
                pub_date=None,
                license=None,
                language="en",
                pdf_uri=destination,
                source="openalex",
                content_hash=None,
            )
            docs.append(doc)
        return docs
