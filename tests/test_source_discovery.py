import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pelota_builder import _extract_ddg_domains

SAMPLE = """
<a class="result__a" href="/l/?uddg=https%3A%2F%2Fexample.com%2Fpage">Example</a>
<a class="result__a" href="/l/?uddg=https%3A%2F%2Ffoo.bar%2F">Foo</a>
<a class="result__a" href="https://direct.example.org/">Direct</a>
"""

def test_extract_ddg_domains():
    domains = _extract_ddg_domains(SAMPLE, limit=5)
    assert "example.com" in domains
    assert "foo.bar" in domains
    assert "direct.example.org" in domains
    assert "duckduckgo.com" not in domains
