"""Render an Invoice to PDF with ReportLab (Platypus)."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import (
    Flowable,
    Image,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from .calc import Totals, compute_totals
from .models import Invoice
from .money import BDT_SYMBOL, format_money, format_number
from .shaping import BanglaShaper, ShapedText, shaping_available
from .words import amount_in_words

try:
    import qrcode
except ImportError:  # pragma: no cover - optional dependency
    qrcode = None

BN_FONT_NAME = "BDInvoiceBangla"
BENGALI_RE = re.compile(r"[ঀ-৿]")
DEFAULT_ACCENTS = {"minimal": "#222222", "modern": "#0f766e"}
PAGE_W, PAGE_H = A4
MARGIN = 18 * mm
CONTENT_W = PAGE_W - 2 * MARGIN


@dataclass
class RenderResult:
    path: str
    number: str
    totals: Totals
    pages: int = 0
    warnings: list = field(default_factory=list)
    bangla: bool = False


def qr_available() -> bool:
    return qrcode is not None


class QRFlowable(Flowable):
    """Vector QR code drawn from the qrcode module's module matrix (no image library needed)."""

    def __init__(self, payload: str, size: float = 28 * mm):
        super().__init__()
        qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=0)
        qr.add_data(payload)
        qr.make(fit=True)
        self.matrix = qr.get_matrix()
        self.size = size
        self.width = self.height = size

    def wrap(self, aw, ah):
        return self.size, self.size

    def draw(self):
        n = len(self.matrix)
        cell = self.size / n
        self.canv.setFillColor(colors.black)
        for r, row in enumerate(self.matrix):
            for c, dark in enumerate(row):
                if dark:
                    self.canv.rect(c * cell, self.size - (r + 1) * cell, cell, cell, stroke=0, fill=1)


def latin_safe(text: str, warnings: list | None = None, where: str = "") -> str:
    """Make text safe for the standard Helvetica font (WinAnsi); unsupported chars become '?'."""
    out = []
    bad = False
    for ch in text:
        try:
            ch.encode("cp1252")
            out.append(ch)
        except UnicodeEncodeError:
            out.append("?")
            bad = True
    if bad and warnings is not None:
        msg = f"unsupported characters replaced with '?'{' in ' + where if where else ''}"
        if BENGALI_RE.search(text):
            msg += " (Bangla text belongs in the *_bn fields and needs --bangla-font)"
        if msg not in warnings:
            warnings.append(msg)
    return "".join(out)


def fmt_qty(value) -> str:
    """12 -> '12', 1.50 -> '1.5' (never scientific notation)."""
    if value == value.to_integral():
        return str(int(value))
    return format(value.normalize(), "f")


def register_bangla_font(path: str) -> bool:
    """Register a Bangla TTF with ReportLab (used for the taka sign). Returns False if unusable."""
    try:
        font = TTFont(BN_FONT_NAME, str(path))
        pdfmetrics.registerFont(font)
    except Exception:
        return False
    return True


def font_has_glyph(char: str) -> bool:
    try:
        face = pdfmetrics.getFont(BN_FONT_NAME).face
    except KeyError:
        return False
    return ord(char) in face.charToGlyph


def hex_color(value: str):
    return colors.HexColor(value if value.startswith("#") else f"#{value}")


class NumberedCanvas(rl_canvas.Canvas):
    """Canvas that can print 'Page x of y' by deferring page output until the total is known."""

    footer_text = ""
    watermark = ""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved: list = []

    def showPage(self):  # noqa: N802
        self._saved.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._saved)
        for state in self._saved:
            self.__dict__.update(state)
            self._draw_footer(total)
            super().showPage()
        super().save()

    def _draw_watermark(self):
        self.saveState()
        self.setFillColor(colors.HexColor("#b0b0b0"))
        self.setFillAlpha(0.22)
        size = min(110.0, 520.0 / max(len(self.watermark), 1) * 1.6)
        self.setFont("Helvetica-Bold", size)
        self.translate(PAGE_W / 2, PAGE_H / 2)
        self.rotate(45)
        self.drawCentredString(0, -size * 0.35, self.watermark)
        self.restoreState()

    def _draw_footer(self, total: int):
        if self.watermark:
            self._draw_watermark()
        self.setFont("Helvetica", 8)
        self.setFillColor(colors.HexColor("#777777"))
        self.drawString(MARGIN, 10 * mm, self.footer_text)
        self.drawRightString(PAGE_W - MARGIN, 10 * mm, f"Page {self._pageNumber} of {total}")


class Renderer:
    def __init__(self, inv: Invoice, totals: Totals, bangla_font: str | None, base_dir: str = "."):
        self.inv, self.t = inv, totals
        self.base_dir = base_dir
        self.warnings: list = []
        self.shaper = None
        self.symbol_ok = False
        self._init_bangla(bangla_font)
        self.accent = hex_color(inv.accent or DEFAULT_ACCENTS[inv.theme])
        self.modern = inv.theme == "modern"
        self.grey = colors.HexColor("#666666")
        self.line = colors.HexColor("#cccccc")
        self.tint = colors.HexColor("#eef6f5") if self.modern else colors.HexColor("#f3f3f3")
        self._styles()

    # -- setup ----------------------------------------------------------
    def _init_bangla(self, font_path):
        if not font_path:
            if self.inv.language == "both":
                self.warnings.append("language 'both' needs --bangla-font; rendering English only")
            return
        if not os.path.isfile(font_path):
            self.warnings.append(f"Bangla font not found: {font_path}; rendering English only")
            return
        if register_bangla_font(font_path) and font_has_glyph(BDT_SYMBOL):
            self.symbol_ok = True
        if shaping_available():
            try:
                self.shaper = BanglaShaper(font_path)
            except Exception as exc:
                self.warnings.append(f"cannot load Bangla font for shaping ({exc}); English only")
        else:
            self.warnings.append(
                "uharfbuzz is not installed, so Bangla text is skipped "
                "(pip install 'bd-invoice[bangla]'); only the taka sign is used"
            )

    def _styles(self):
        def ps(name, **kw):
            base = dict(fontName="Helvetica", fontSize=9, leading=12, textColor=colors.black)
            base.update(kw)
            return ParagraphStyle(name, **base)

        self.s = {
            "body": ps("body"),
            "small": ps("small", fontSize=8, leading=10.5, textColor=self.grey),
            "right": ps("right", alignment=TA_RIGHT),
            "center": ps("center", alignment=TA_CENTER),
            "bold": ps("bold", fontName="Helvetica-Bold"),
            "bold_right": ps("bold_right", fontName="Helvetica-Bold", alignment=TA_RIGHT),
            "label": ps("label", fontSize=7.5, leading=10, textColor=self.grey, fontName="Helvetica-Bold"),
            "title": ps("title", fontName="Helvetica-Bold", fontSize=22, leading=26,
                        textColor=self.accent, alignment=TA_RIGHT),  # fmt: skip
            "seller": ps("seller", fontName="Helvetica-Bold", fontSize=14, leading=17),
            "th": ps("th", fontName="Helvetica-Bold", fontSize=8.5, textColor=(
                colors.white if self.modern else colors.black)),
            "th_right": ps("th_right", fontName="Helvetica-Bold", fontSize=8.5, alignment=TA_RIGHT,
                           textColor=colors.white if self.modern else colors.black),  # fmt: skip
        }  # fmt: skip

    # -- text helpers -----------------------------------------------------
    def tx(self, text: str, where: str = "") -> str:
        return escape(latin_safe(str(text), self.warnings, where))

    def money(self, value, currency=None) -> str:
        """Markup string for an amount; the taka sign is drawn with the Bangla font."""
        cur = currency or self.inv.currency
        text = format_money(value, cur, unicode_ok=self.symbol_ok)
        if self.symbol_ok and text.startswith(BDT_SYMBOL):
            return f'<font name="{BN_FONT_NAME}">{BDT_SYMBOL}</font> {escape(text[1:])}'
        return escape(text)

    def para(self, markup: str, style="body") -> Paragraph:
        return Paragraph(markup, self.s[style])

    def bn_line(self, text: str, size=9, color=None, align="left"):
        if not (self.shaper and text):
            return None
        return ShapedText(text, self.shaper, size=size, color=color or colors.black, align=align)

    # -- sections ---------------------------------------------------------
    def header(self) -> list:
        inv = self.inv
        left: list = []
        logo = self._logo()
        if logo is not None:
            left.append(logo)
            left.append(Spacer(1, 3 * mm))
        left.append(self.para(self.tx(inv.seller.name, "seller.name"), "seller"))
        bn = self.bn_line(inv.seller.name_bn, 11) if inv.language == "both" else None
        if bn is not None:
            left.append(bn)

        right: list = [self.para(inv.title, "title")]
        if inv.language == "both":
            bn_title = self.bn_line(
                "কোটেশন" if inv.doc_type == "quotation" else "চালান", 12, self.accent, "right"
            )
            if bn_title is not None:
                right.append(bn_title)
        meta = [["No.", inv.number], ["Date", inv.issue_date.strftime("%d %b %Y")]]
        if inv.due_date:
            meta.append(["Due date", inv.due_date.strftime("%d %b %Y")])
        if inv.valid_until:
            meta.append(["Valid until", inv.valid_until.strftime("%d %b %Y")])
        if inv.payment_terms:
            meta.append(["Terms", inv.payment_terms])
        if inv.reference:
            meta.append(["Reference", inv.reference])
        rows = [[self.para(f"<b>{self.tx(k)}</b>"), self.para(self.tx(v, k), "right")] for k, v in meta]
        meta_t = Table(rows, colWidths=[24 * mm, 46 * mm])
        meta_t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                                    ("TOPPADDING", (0, 0), (-1, -1), 1),
                                    ("BOTTOMPADDING", (0, 0), (-1, -1), 1)]))  # fmt: skip
        right.append(Spacer(1, 2 * mm))
        right.append(meta_t)

        head = Table([[left, right]], colWidths=[CONTENT_W * 0.5, CONTENT_W * 0.5])
        head.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                                  ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                  ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                                  ("LINEBELOW", (0, 0), (-1, 0), 1.2, self.accent),
                                  ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))  # fmt: skip
        return [head, Spacer(1, 6 * mm)]

    def _logo(self):
        path = self.inv.logo
        if not path:
            return None
        full = path if os.path.isabs(path) else os.path.join(self.base_dir, path)
        if not os.path.isfile(full):
            self.warnings.append(f"logo not found: {path}")
            return None
        try:
            img = Image(full)
            max_w, max_h = 45 * mm, 18 * mm
            ratio = min(max_w / img.imageWidth, max_h / img.imageHeight, 1.0)
            img.drawWidth, img.drawHeight = img.imageWidth * ratio, img.imageHeight * ratio
            img.hAlign = "LEFT"
            return img
        except Exception as exc:
            self.warnings.append(f"cannot read logo {path}: {exc.__class__.__name__}")
            return None

    def party_block(self, label: str, party) -> list:
        out: list = [self.para(label.upper(), "label"), self.para(f"<b>{self.tx(party.name, label)}</b>")]
        if self.inv.language == "both":
            bn = self.bn_line(party.name_bn, 9.5)
            if bn is not None:
                out.append(bn)
        for line in party.address:
            out.append(self.para(self.tx(line, label)))
        for text in (party.email, party.phone):
            if text:
                out.append(self.para(self.tx(text, label)))
        if party.tax_id:
            out.append(self.para(f"{self.tx(party.tax_id_label)}: {self.tx(party.tax_id, label)}"))
        return out

    def parties(self) -> list:
        t = Table(
            [[self.party_block("From", self.inv.seller), self.party_block("Bill to", self.inv.buyer)]],
            colWidths=[CONTENT_W * 0.5, CONTENT_W * 0.5],
        )
        t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                               ("LEFTPADDING", (0, 0), (-1, -1), 0)]))  # fmt: skip
        return [t, Spacer(1, 7 * mm)]

    def items_table(self) -> Table:
        inv, t = self.inv, self.t
        show_disc = any(i.discount_percent for i in inv.items)
        head = ["#", "Description", "Qty", "Unit price"] + (["Disc."] if show_disc else []) + ["Amount"]
        aligns = (
            ["th_right", "th", "th_right", "th_right"] + (["th_right"] if show_disc else []) + ["th_right"]
        )
        rows = [[self.para(self.tx(h), a) for h, a in zip(head, aligns)]]
        for idx, (item, line) in enumerate(zip(inv.items, t.lines), start=1):
            desc = f"{self.tx(item.description, f'item {idx}')}"
            qty = fmt_qty(item.quantity)
            if item.unit:
                qty += f" {self.tx(item.unit)}"
            cell: list = [self.para(desc)]
            if inv.language == "both" and item.description_bn:
                bn = self.bn_line(item.description_bn, 8.5)
                if bn is not None:
                    cell.append(bn)
            row = [
                self.para(str(idx), "right"),
                cell,
                self.para(qty, "right"),
                self.para(escape(format_number(item.unit_price, inv.currency)), "right"),
            ]
            if show_disc:
                row.append(
                    self.para(
                        f"{item.discount_percent.normalize():f}%" if item.discount_percent else "-", "right"
                    )
                )
            row.append(self.para(escape(format_number(line.net, inv.currency)), "right"))
            rows.append(row)
        widths = [9 * mm, None, 22 * mm, 28 * mm] + ([16 * mm] if show_disc else []) + [30 * mm]
        fixed = sum(w for w in widths if w)
        widths[1] = CONTENT_W - fixed
        table = Table(rows, colWidths=widths, repeatRows=1)
        style = [
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LINEBELOW", (0, 1), (-1, -1), 0.4, self.line),
        ]
        if self.modern:
            style += [("BACKGROUND", (0, 0), (-1, 0), self.accent)]
        else:
            style += [("LINEABOVE", (0, 0), (-1, 0), 0.8, colors.black),
                      ("LINEBELOW", (0, 0), (-1, 0), 0.8, colors.black)]  # fmt: skip
        table.setStyle(TableStyle(style))
        return table

    def totals_block(self) -> Table:
        inv, t = self.inv, self.t
        rows = [("Subtotal", self.money(t.subtotal), False)]
        if t.discount:
            label = inv.discount.label if inv.discount else "Discount"
            if inv.discount and inv.discount.kind == "percent":
                label += f" ({inv.discount.value.normalize():f}%)"
            rows.append((label, "-" + self.money(t.discount), False))
            rows.append(("Amount after discount", self.money(t.taxable), False))
        if inv.vat_percent:
            rows.append((f"{inv.vat_label} ({inv.vat_percent.normalize():f}%)", self.money(t.vat), False))
        rows.append(("Total", self.money(t.total), True))
        for label, pct, amount in t.deductions:
            rows.append((f"Less: {label} ({pct.normalize():f}%)", "-" + self.money(amount), False))
        if t.deductions:
            title = "Net payable" if inv.doc_type == "invoice" else "Net amount"
            rows.append((title, self.money(t.net_payable), True))
        data = [
            [self.para(self.tx(label, "totals"), "bold" if bold else "body"),
             self.para(value, "bold_right" if bold else "right")]
            for label, value, bold in rows
        ]  # fmt: skip
        table = Table(data, colWidths=[52 * mm, 38 * mm], hAlign="RIGHT")
        style = [("TOPPADDING", (0, 0), (-1, -1), 2.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5)]
        for i, (_, _, bold) in enumerate(rows):
            if bold:
                style.append(("LINEABOVE", (0, i), (-1, i), 0.6, self.accent))
        last = len(rows) - 1
        style.append(("BACKGROUND", (0, last), (-1, last), self.tint))
        table.setStyle(TableStyle(style))
        return table

    def words_block(self) -> list:
        inv, t = self.inv, self.t
        amount = t.net_payable
        label = "AMOUNT PAYABLE IN WORDS" if inv.doc_type == "invoice" else "TOTAL IN WORDS"
        out: list = [self.para(label, "label"),
                     self.para(escape(amount_in_words(amount, inv.currency, "en")), "bold")]  # fmt: skip
        if inv.language == "both" and self.shaper:
            try:
                out.append(self.bn_line(amount_in_words(amount, inv.currency, "bn"), 10))
            except ValueError:
                pass
        return out

    def payment_block(self) -> list:
        p = self.inv.payment
        lines: list = []
        for key, value in p.bank.items():
            lines.append(f"<b>{self.tx(key.replace('_', ' ').title())}:</b> {self.tx(value, 'payment')}")
        if p.bkash:
            lines.append(f"<b>bKash:</b> {self.tx(p.bkash, 'payment')}")
        if p.nagad:
            lines.append(f"<b>Nagad:</b> {self.tx(p.nagad, 'payment')}")
        for text in p.other:
            lines.append(self.tx(text, "payment"))
        qr_cell: list = []
        if p.qr:
            if qrcode is None:
                self.warnings.append(
                    "QR requested but 'qrcode' is not installed (pip install 'bd-invoice[qr]')"
                )
            else:
                qr_cell = [QRFlowable(self.qr_payload()),
                           Spacer(1, 1 * mm),
                           self.para(f"Ref: {self.tx(self.inv.number)}", "small")]  # fmt: skip
        if not lines and not qr_cell:
            return []
        left: list = [self.para("PAYMENT INSTRUCTIONS", "label")] + [self.para(ln) for ln in lines]
        table = Table([[left, qr_cell]], colWidths=[CONTENT_W - 40 * mm, 40 * mm])
        table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                                   ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                   ("BOX", (0, 0), (-1, -1), 0.5, self.line),
                                   ("LEFTPADDING", (0, 0), (0, 0), 6),
                                   ("TOPPADDING", (0, 0), (-1, -1), 6),
                                   ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))  # fmt: skip
        return [KeepTogether([table])]

    def qr_payload(self) -> str:
        if self.inv.payment.qr_payload:
            return self.inv.payment.qr_payload
        inv = self.inv
        return f"REF:{inv.number}|AMT:{self.t.net_payable:.2f}|CUR:{inv.currency}|PAYEE:{inv.seller.name}"

    def notes(self) -> list:
        out: list = []
        if self.inv.notes:
            out += [Spacer(1, 4 * mm), self.para("NOTES", "label")]
            for line in self.inv.notes.splitlines():
                out.append(self.para(self.tx(line, "notes")))
        if self.inv.terms:
            out += [Spacer(1, 3 * mm), self.para("TERMS", "label")]
            out += [self.para(f"- {self.tx(t, 'terms')}", "small") for t in self.inv.terms]
        return out

    # -- build ------------------------------------------------------------
    def story(self) -> list:
        story = self.header() + self.parties()
        story.append(self.items_table())
        story.append(Spacer(1, 5 * mm))
        summary = Table([[self.words_block(), self.totals_block()]],
                        colWidths=[CONTENT_W - 94 * mm, 94 * mm])  # fmt: skip
        summary.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                                     ("LEFTPADDING", (0, 0), (0, 0), 0),
                                     ("RIGHTPADDING", (0, 0), (0, 0), 8)]))  # fmt: skip
        story.append(KeepTogether([summary]))
        pay = self.payment_block()
        if pay:
            story.append(Spacer(1, 6 * mm))
            story += pay
        story += self.notes()
        return story


def render_invoice(
    inv: Invoice, out_path, bangla_font: str | None = None, base_dir: str = "."
) -> RenderResult:
    """Render `inv` to `out_path` and return details (page count, warnings)."""
    totals = compute_totals(inv)
    r = Renderer(inv, totals, bangla_font, base_dir)

    class Canvas(NumberedCanvas):
        footer_text = f"{inv.title.title()} {inv.number}  |  {inv.seller.name}"[:110]

    Canvas.footer_text = latin_safe(Canvas.footer_text)
    Canvas.watermark = inv.watermark
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(out),
        pagesize=A4,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN,
        bottomMargin=20 * mm,
        title=f"{inv.title.title()} {inv.number}",
        author=latin_safe(inv.seller.name),
        subject=f"{inv.title.title()} for {latin_safe(inv.buyer.name)}",
        creator="bd-invoice",
    )
    doc.build(r.story(), canvasmaker=Canvas)
    return RenderResult(
        path=str(out),
        number=inv.number,
        totals=totals,
        pages=doc.page,
        warnings=r.warnings,
        bangla=bool(r.shaper),
    )
