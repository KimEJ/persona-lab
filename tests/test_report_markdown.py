"""The standalone product document keeps editor formatting without active HTML."""
import unittest
from html.parser import HTMLParser

from persona_desktop.report_markdown import render_markdown


class TagCollector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = []
        self.links = []

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        if tag == 'a':
            self.links.append(dict(attrs)['href'])


class ReportMarkdownTests(unittest.TestCase):
    def test_escapes_hostile_html_and_rejects_executable_links(self):
        document = ('<script>alert(1)</script> <img src=x onerror=alert(2)>\n'
                    '[run](javascript:alert) [data](data:text/html,evil)\n'
                    '[safe **site**](https://example.test/?a=1&b="quoted")\n'
                    '![external image](https://example.test/image.png)\n'
                    '`<iframe src="https://example.test">`\n'
                    '[bad](https://[invalid) [relative](/local)')
        rendered = render_markdown(document)
        parser = TagCollector()
        parser.feed(rendered)
        self.assertFalse({'script', 'img', 'iframe'} & set(parser.tags))
        self.assertEqual(parser.links, ['https://example.test/?a=1&b="quoted"'])
        self.assertIn('&lt;script&gt;', rendered)
        self.assertIn('[run](javascript:alert)', rendered)
        self.assertIn('[data](data:text/html,evil)', rendered)
        self.assertIn('![external image](https://example.test/image.png)', rendered)
        self.assertIn('<strong>site</strong>', rendered)
        self.assertIn('<code>&lt;iframe', rendered)

    def test_tables_keep_escaped_pipes_alignment_and_inline_formatting(self):
        document = ('| 기능 | 값 | 비고 |\n| :--- | ---: | :---: |\n'
                    '| 검색 \\| 정렬 | **120** | `<b>` |\n'
                    '| 보관 | 24 | 기본 | 추가 |')
        rendered = render_markdown(document)
        self.assertIn('<th class="md-left">기능</th>', rendered)
        self.assertIn('<th class="md-right">값</th>', rendered)
        self.assertIn('<th class="md-center">비고</th>', rendered)
        self.assertIn('<td class="md-left">검색 | 정렬</td>', rendered)
        self.assertIn('<strong>120</strong>', rendered)
        self.assertIn('<code>&lt;b&gt;</code>', rendered)
        self.assertIn('기본 | 추가', rendered)
        self.assertEqual(rendered.count('<tr>'), 3)

    def test_nested_lists_and_fences_preserve_structure_and_code(self):
        document = ('- 기본\n  3. 작은 항목\n  4. 다음 항목\n- 추가\n\n'
                    '~~~~ py\n<script>\n```\n~~~~\n\n'
                    '> *참고*\n\n---\n\n끝\n다음 줄\n\n```\n미완료 <code>')
        rendered = render_markdown(document)
        self.assertIn('<ul><li>기본<ol start="3"><li>작은 항목</li><li>다음 항목</li></ol></li><li>추가</li></ul>', rendered)
        self.assertIn('<pre><code>&lt;script&gt;\n```</code></pre>', rendered)
        self.assertIn('<blockquote><p><em>참고</em></p></blockquote>', rendered)
        self.assertIn('<hr>', rendered)
        self.assertIn('<p>끝<br>다음 줄</p>', rendered)
        self.assertTrue(rendered.endswith('<pre><code>미완료 &lt;code&gt;</code></pre>'))

    def test_supplied_title_removes_only_matching_initial_h1(self):
        self.assertEqual(render_markdown('\n# 상품 A\n\n## 기능\n내용', '상품 A'), '<h2>기능</h2><p>내용</p>')
        self.assertIn('<h1>상품 B</h1>', render_markdown('# 상품 B\n내용', '상품 A'))
        self.assertIn('<h2>상품 A</h2>', render_markdown('## 상품 A\n내용', '상품 A'))
        self.assertIn('<h1>상품 A</h1>', render_markdown('먼저 나온 내용\n# 상품 A', '상품 A'))
        self.assertIn('<h1>상품 A</h1>', render_markdown('# 상품 A\n내용'))
        self.assertEqual(render_markdown(''), '')


if __name__ == '__main__':
    unittest.main()
