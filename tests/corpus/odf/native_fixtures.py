"""Small deterministic ODF controls authored directly, without an Office exporter.

These are synthetic regression fixtures, not a real-world document corpus.
"""
from pathlib import Path
import struct
import zlib
import zipfile

NS = '''xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"
xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0"
xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0"
xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0"
xmlns:number="urn:oasis:names:tc:opendocument:xmlns:datastyle:1.0"
xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0"
xmlns:svg="urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0"
xmlns:xlink="http://www.w3.org/1999/xlink"'''


def png():
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
    # Red and transparent pixels over blue and green pixels.
    pixels = b'\0\xff\0\0\xff\0\0\0\0\0\0\0\xff\xff\0\xff\0\xff'
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 2, 2, 8, 6, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(pixels)) + chunk(b'IEND', b''))


def package(path, kind, body, automatic='', styles='', master=''):
    mime = 'application/vnd.oasis.opendocument.' + kind
    if kind == 'text':
        styles = '<style:default-style style:family="paragraph"><style:text-properties fo:font-family="Liberation Serif" fo:font-size="12pt"/></style:default-style>' + styles
    content = f'<office:document-content {NS} office:version="1.2"><office:automatic-styles>{automatic}</office:automatic-styles><office:body>{body}</office:body></office:document-content>'
    style_xml = f'<office:document-styles {NS} office:version="1.2"><office:styles>{styles}</office:styles><office:automatic-styles><style:page-layout style:name="Page"><style:page-layout-properties fo:page-width="10in" fo:page-height="7.5in" fo:margin="0.5in"/></style:page-layout></office:automatic-styles><office:master-styles><style:master-page style:name="Standard" style:page-layout-name="Page">{master}</style:master-page></office:master-styles></office:document-styles>'
    manifest = f'<manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0" manifest:version="1.2"><manifest:file-entry manifest:full-path="/" manifest:media-type="{mime}"/><manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml"/><manifest:file-entry manifest:full-path="styles.xml" manifest:media-type="text/xml"/><manifest:file-entry manifest:full-path="Pictures/test.png" manifest:media-type="image/png"/></manifest:manifest>'
    entries = {'mimetype': mime.encode(), 'content.xml': content.encode(), 'styles.xml': style_xml.encode(),
               'Pictures/test.png': png(), 'META-INF/manifest.xml': manifest.encode()}
    with zipfile.ZipFile(path, 'w') as archive:
        for name, data in entries.items():
            info = zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_STORED if name == 'mimetype' else zipfile.ZIP_DEFLATED
            archive.writestr(info, data)


def build(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    package(directory / 'native-writer.odt', 'text', '''<office:text>
<text:p>Native ODT control</text:p>
<text:p><text:span text:style-name="Emphasis">Styled blue text</text:span></text:p>
<text:list><text:list-item><text:p>First paragraph</text:p><text:p>Second paragraph</text:p><text:list><text:list-item><text:p>Nested item</text:p></text:list-item></text:list></text:list-item></text:list>
<text:p><draw:frame text:anchor-type="as-char" svg:width="1cm" svg:height="1cm"><draw:image xlink:href="Pictures/test.png"/><svg:desc>Accessible image description</svg:desc></draw:frame></text:p>
<text:p text:style-name="Break">Second page body</text:p></office:text>''',
            automatic='''<style:style style:name="Break" style:family="paragraph"><style:paragraph-properties fo:break-before="page"/></style:style><style:style style:name="Emphasis" style:family="text"><style:text-properties fo:font-size="18pt" fo:font-weight="bold" fo:color="#1751a8"/></style:style>''',
            master='''<style:header><text:p>Later page header</text:p></style:header><style:header-first><text:p>First page header</text:p></style:header-first><style:footer><text:p>Page <text:page-number>1</text:page-number> of <text:page-count>2</text:page-count></text:p></style:footer><style:footer-first><text:p>Page <text:page-number>1</text:page-number> of <text:page-count>2</text:page-count></text:p></style:footer-first>''')
    package(directory / 'native-impress.odp', 'presentation', '''<office:presentation><draw:page draw:name="Native" draw:style-name="Canvas" draw:master-page-name="Standard">
<draw:frame draw:style-name="Clear" svg:x="1in" svg:y="0.5in" svg:width="6in" svg:height="1in"><draw:text-box><text:p>Native ODP control</text:p><text:p>Before <text:span>middle</text:span> after</text:p></draw:text-box></draw:frame>
<draw:rect draw:style-name="Blue" svg:x="1in" svg:y="2in" svg:width="2in" svg:height="2in"/>
<draw:frame svg:x="1in" svg:y="2in" svg:width="2in" svg:height="2in"><draw:image xlink:href="Pictures/test.png"/><svg:desc>Transparent image</svg:desc></draw:frame>
<draw:g><draw:frame draw:style-name="Clear" svg:x="4in" svg:y="2in" svg:width="4in" svg:height="2in"><draw:text-box><text:list><text:list-item><text:p>Outer item</text:p><text:list><text:list-item><text:p>Nested item</text:p></text:list-item></text:list></text:list-item></text:list></draw:text-box></draw:frame></draw:g>
</draw:page></office:presentation>''', automatic='''<style:style style:name="Canvas" style:family="drawing-page"><style:drawing-page-properties draw:fill="solid" draw:fill-color="#f4f4f4"/></style:style><style:style style:name="Clear" style:family="graphic"><style:graphic-properties draw:fill="none" draw:stroke="none"/></style:style><style:style style:name="Blue" style:family="graphic"><style:graphic-properties draw:fill="solid" draw:fill-color="#1751a8" draw:stroke="none"/></style:style>''')
    package(directory / 'native-calc.ods', 'spreadsheet', '''<office:spreadsheet><table:table table:name="Visible" table:style-name="Visible">
<table:table-column table:style-name="Wide" table:number-columns-repeated="3"/>
<table:table-header-rows><table:table-row><table:table-cell office:value-type="string"><text:p>Native ODS control</text:p></table:table-cell></table:table-row></table:table-header-rows>
<table:table-row><table:table-cell table:style-name="PercentCell" office:value-type="percentage" office:value="0.125"><text:p>12.5%</text:p></table:table-cell><table:table-cell table:style-name="CurrencyCell" office:value-type="currency" office:currency="USD" office:value="-12.5"><text:p>-$12.50</text:p></table:table-cell><table:table-cell table:style-name="DateCell" office:value-type="date" office:date-value="2024-02-29"><text:p>29-Feb-2024</text:p></table:table-cell></table:table-row>
<table:table-row table:number-rows-repeated="2"><table:table-cell office:value-type="string"><text:p>Repeated row</text:p></table:table-cell></table:table-row>
<table:table-row><table:table-cell table:style-name="Border" table:number-columns-spanned="2" office:value-type="string"><text:p>Merged cell</text:p></table:table-cell><table:covered-table-cell/><table:table-cell office:value-type="string"><text:p>Tail cell</text:p></table:table-cell></table:table-row>
<table:table-row table:style-name="Tall"><table:table-cell table:style-name="Wrapped" office:value-type="string"><text:p>Wrapped words stay within cell</text:p></table:table-cell></table:table-row>
</table:table><table:table table:name="Hidden" table:style-name="Hidden"><table:table-row><table:table-cell office:value-type="string"><text:p>Hidden sentinel</text:p></table:table-cell></table:table-row></table:table></office:spreadsheet>''',
            automatic='''<number:percentage-style style:name="Percent"><number:number number:decimal-places="1" number:min-integer-digits="1"/><number:text>%</number:text></number:percentage-style><number:currency-style style:name="Currency"><number:currency-symbol number:language="en" number:country="US">$</number:currency-symbol><number:number number:decimal-places="2" number:min-integer-digits="1"/></number:currency-style><style:style style:name="PercentCell" style:family="table-cell" style:data-style-name="Percent"/><style:style style:name="CurrencyCell" style:family="table-cell" style:data-style-name="Currency"/><number:date-style style:name="Date"><number:day number:style="long"/><number:text>-</number:text><number:month number:textual="true" number:style="short"/><number:text>-</number:text><number:year number:style="long"/></number:date-style><style:style style:name="DateCell" style:family="table-cell" style:data-style-name="Date"/><style:style style:name="Border" style:family="table-cell"><style:table-cell-properties fo:border="0.75pt solid #1751a8" fo:background-color="#e0efff"/></style:style><style:style style:name="Wrapped" style:family="table-cell"><style:table-cell-properties fo:wrap-option="wrap"/></style:style><style:style style:name="Tall" style:family="table-row"><style:table-row-properties style:row-height="0.5in"/></style:style><style:style style:name="Wide" style:family="table-column"><style:table-column-properties style:column-width="1.5in"/></style:style><style:style style:name="Visible" style:family="table" style:master-page-name="Standard"/><style:style style:name="Hidden" style:family="table"><style:table-properties table:display="false"/></style:style>''')
    return sorted(directory.glob('native-*.*'))
