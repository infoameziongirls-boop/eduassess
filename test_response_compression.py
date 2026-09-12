import gzip
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app


@app.route('/_test-compression')
def compression_response():
    return '<html>' + ('student roster ' * 200) + '</html>'


def test_large_html_response_is_gzipped_for_supported_clients():
    payload = '<html>' + ('student roster ' * 200) + '</html>'

    client = app.test_client()
    response = client.get('/_test-compression', headers={'Accept-Encoding': 'gzip'})

    assert response.status_code == 200
    assert response.headers['Content-Encoding'] == 'gzip'
    assert 'Accept-Encoding' in response.headers['Vary']
    assert gzip.decompress(response.data).decode() == payload


def test_response_is_not_gzipped_without_client_support():
    payload = '<html>' + ('student roster ' * 200) + '</html>'

    client = app.test_client()
    response = client.get('/_test-compression', headers={'Accept-Encoding': 'identity'})

    assert response.status_code == 200
    assert 'Content-Encoding' not in response.headers
    assert response.data.decode() == payload