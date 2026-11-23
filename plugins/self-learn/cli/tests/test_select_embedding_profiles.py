"""Task query/document embedding calls use bounded, private request profiles."""
import urllib.error

import pytest

from self_learn.index.gemini import GeminiEmbedder, GeminiEmbedError, format_document_text, format_query_text
from self_learn.index.textquery import embed_documents


@pytest.mark.parametrize('query', [False, True])
def test_interactive_request_is_one_attempt_without_changing_shared_profiles(query):
    calls = []
    def transport(action, body, timeout):
        calls.append((body, timeout))
        raise urllib.error.HTTPError('synthetic', 503, 'synthetic retryable failure', {}, None)
    provider = GeminiEmbedder(dim=2, api_key='synthetic', transport=transport, sleep=lambda _: None)
    bulk, interactive = provider.bulk, provider.interactive
    before = (bulk.max_attempts, bulk.timeout, bulk.paced,
              interactive.max_attempts, interactive.timeout, interactive.paced)
    with pytest.raises(GeminiEmbedError):
        embed_documents(provider, ['Amber registry'], interactive=True, query=query)
    assert len(calls) == 1
    body, timeout = calls[0]
    template = format_query_text if query else format_document_text
    assert body['requests'][0]['content']['parts'][0]['text'] == template('Amber registry')
    assert timeout <= 5.0
    assert provider.bulk is bulk and provider.interactive is interactive
    assert (bulk.max_attempts, bulk.timeout, bulk.paced,
            interactive.max_attempts, interactive.timeout, interactive.paced) == before
