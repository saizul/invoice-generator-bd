# bd-invoice

Professional **PDF invoices and quotations for Bangladeshi freelancers and agencies**, generated from a
YAML file (or a CSV for batches). VAT, AIT/withholding lines, BDT with lakh/crore grouping, USD and other
currencies, amount in words in English and Bangla ("Taka ... Only" / "টাকা ... মাত্র"), local invoice
numbering, bKash / Nagad / bank instruction blocks, optional QR code, logo and two themes.

Built by [Saizul Amin](https://saizul.com). MIT licensed. All example data is synthetic.

A generated sample is in [`examples/sample-invoice.pdf`](examples/sample-invoice.pdf) (BDT, VAT, AIT,
Bangla) and [`examples/sample-quotation.pdf`](examples/sample-quotation.pdf) (USD).

## Features

- **Money done right**: all arithmetic uses `Decimal` with explicit `ROUND_HALF_UP` to 2 places. Floats never
  touch the calculations.
- **BDT formatting**: `12,34,567.50` (South Asian grouping); USD/EUR/GBP use `1,234,567.50`.
- **Totals**: line discounts, a document discount (percent or fixed), VAT (configurable, e.g. 15%) on the
  discounted amount, then any number of withholding lines (AIT, VDS, ...) on the taxable amount or on the
  VAT-inclusive total, then **net payable**.
- **Amount in words**: English with lakh/crore for BDT ("Taka One Lakh Twenty Thousand Only") and Bangla
  ("টাকা এক লক্ষ বিশ হাজার মাত্র"), including paisa.
- **Numbering**: `INV-{YYYY}-{seq:04}` style patterns with a local JSON counter file that resets
  never/yearly/monthly; quotations use their own `QT-` counter.
- **Due date / validity**: `payment_terms: Net 15` or an explicit date; quotations get `valid_until`.
- **Payment block** (text only): bank, bKash, Nagad and free lines; optional QR with a payment reference.
- **Themes**: `minimal` and `modern` (with a custom `accent` colour). Logo image support.
- **Batch**: one CSV (a row per line item) plus a YAML profile produces many PDFs.
- Multi-page tables with repeated headers and "Page x of y" footers.

## Install

```bash
pip install .                    # core: reportlab + PyYAML (Python 3.10+)
pip install ".[qr]"              # optional QR code on the invoice
pip install ".[bangla]"          # optional Bangla shaping (uharfbuzz)
pip install ".[all]"             # everything
```

## Quick start

```bash
bd-invoice sample > invoice.yaml           # starter file
bd-invoice generate invoice.yaml           # -> INV-2026-0001.pdf, counter advances
bd-invoice generate invoice.yaml -o out/march.pdf --theme minimal
bd-invoice words 1234567.50                # English and Bangla words
bd-invoice number --peek                   # what number comes next?
bd-invoice batch examples/clients.csv --profile examples/profile.yaml --out-dir invoices/
```

See [`examples/invoice-bdt.yaml`](examples/invoice-bdt.yaml) for every supported field. In short:

```yaml
type: invoice            # or quotation
currency: BDT
issue_date: 2026-03-01
payment_terms: Net 15
vat_percent: 15
ait_percent: 5           # or a list: withholdings: [{label: VDS, percent: 7.5, base: total}]
seller: {name: ..., address: [...], email: ..., phone: ..., tax_id: ...}
buyer:  {name: ..., address: [...]}
items:
  - {description: SEO audit, quantity: 1, unit_price: 25000}
discount: {type: percent, value: 5}
payment: {bank: {bank_name: ...}, bkash: "01700-000000", qr: true}
```

The amount in words is for the **net payable** (after withholdings), which is the money you expect to receive.

### CSV batches

One row per line item. Rows with the same `invoice` value become one document. Required columns:
`buyer_name`, `description`, `unit_price`. Optional: `invoice`, `buyer_address` (use `|` for line breaks),
`buyer_email`, `buyer_phone`, `buyer_tax_id`, `quantity`, `unit`, `discount_percent`, `issue_date`, `due_date`,
`currency`, `vat_percent`, `ait_percent`, `reference`, `notes`, `type`, `theme`, `number`. Everything else
(seller, payment, defaults) comes from the `--profile` YAML. A failing invoice is reported and the rest continue.

## Bangla text (fonts are not bundled)

The tool ships **no fonts**. To print Bangla (Bangla title, `name_bn`, `description_bn`, Bangla amount in
words and the ৳ sign) you supply a Bangla TTF yourself, for example the free *Noto Sans Bengali* /
*Noto Serif Bengali* (SIL Open Font License) from Google Fonts. Use a **static** TTF (not a variable font).

```bash
pip install ".[bangla]"
bd-invoice generate invoice.yaml --bangla-font /path/to/NotoSansBengali-Regular.ttf
# or: export BD_INVOICE_BANGLA_FONT=/path/to/NotoSansBengali-Regular.ttf
```

Set `language: both` in the YAML to turn the Bangla lines on.

Why `uharfbuzz`? ReportLab cannot shape complex scripts: vowel signs and conjuncts (যুক্তাক্ষর) would come out
in the wrong order. With `uharfbuzz` installed, Bangla runs are shaped by HarfBuzz and drawn as vector glyph
outlines. Consequences: the output is visually correct, but Bangla text is not selectable or searchable.
English text stays normal, selectable PDF text.

Graceful fallback: with no font (or a bad path, or no `uharfbuzz`) the PDF is still produced in English only
and a warning is printed. Bangla characters typed into plain English fields are replaced by `?` with a warning.
Without a font the taka sign is written as `BDT`.

The bundled `examples/sample-invoice.pdf` was rendered with Noto Serif Bengali (OFL) to show the output.

## Numbering

```
--number-pattern "INV-{YYYY}-{seq:04}"   tokens: {YYYY} {YY} {MM} {DD} {seq} {seq:N}
--reset yearly|monthly|never
--counter-file .bd-invoice-counter.json
```

A `number:` in the YAML always wins and does not touch the counter. `--no-count` peeks without advancing.
The counter file is written atomically (temp file + rename); it is meant for a single user on one machine.
A number is issued after the input validates, so a bad file never burns a number (a later PDF-writing
failure could).

## Notes on tax

VAT and AIT percentages are inputs you configure; the tool does not know current NBR rules, rates, or whether
VAT applies to your services, and the QR code is a plain-text payment reference, not a bKash/Nagad/BD-QR
payload. Check with your accountant. This is not tax advice.

## Development

```bash
pip install -e ".[dev]"
ruff check .
pytest
BD_INVOICE_TEST_FONT=/path/to/NotoSansBengali-Regular.ttf pytest   # also runs Bangla rendering tests
```

## License

MIT, see [LICENSE](LICENSE).
