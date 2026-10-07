from app.tools.literature.models import Paper


def open_access_pdf_url(paper: Paper) -> str | None:
    """The paper's explicit open-access PDF location, if a provider reported one.

    Only URLs the academic providers list as open-access PDFs (OpenAlex best_oa_location,
    Semantic Scholar openAccessPdf) are used. Landing pages are never scraped and paywalls,
    logins or publisher access controls are never bypassed; without such a URL the caller
    falls back to the abstract.
    """
    url = paper.oa_pdf_url
    if url and url.startswith(("https://", "http://")):
        return url
    return None
