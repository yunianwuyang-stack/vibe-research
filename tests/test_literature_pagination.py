import json
from infrastructure.literature import HttpTransport

RAW = {"title": "A Study", "authors": ["Doe, J."], "year": 2024, "doi": "10.1000/abc", "url": "https://example.test/a"}


def test_http_transport_fetches_multiple_pages_until_short_page():
    calls = []
    def item(title):
        return {"title": title, "id": "https://openalex.org/W1", "publication_year": 2024, "authorships": [], "doi": "https://doi.org/10.1000/abc"}
    payloads = [{"results": [item("one"), item("two")]}, {"results": [item("three")]}]

    class Response:
        status = 200
        def __init__(self, payload): self.payload = payload
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def read(self): return json.dumps(self.payload).encode()

    def opener(request, timeout):
        calls.append(request.full_url)
        return Response(payloads[len(calls) - 1])

    records = HttpTransport(opener=opener, page_size=2, max_results=10).get_json("openalex", "paged", 1)
    assert len(records) == 3
    assert len(calls) == 2
    assert "page=2" in calls[1]
