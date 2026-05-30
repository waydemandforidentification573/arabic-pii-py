#!/usr/bin/env python3
"""Build & verify the REAL GCC PII eval corpus gold files.

For each fixture we hold a list of (kind, value, occurrence_index, source_url,
note). Byte offsets are computed against the raw UTF-8 bytes of the .txt with
``data.find(value.encode(), cursor)`` so multi-byte Arabic can never cause an
off-by-one. Each slice is asserted to round-trip before its JSONL line is
written. README manifest rows are emitted from the SAME structure, so gold and
manifest cannot drift.

Run from anywhere:  python3 tests/eval/real/build_gold.py
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CORPUS = os.path.join(HERE, "corpus")
GOLD = os.path.join(HERE, "gold")
REPO_ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, REPO_ROOT)
from apii.checksums import iban_mod97  # noqa: E402

FLOOR = 0.85

# kind, value, occurrence_index (0-based among identical strings in this file),
#   source_url, note
SPECS = {
    "iban_calculator_faq.txt": [
        ("IBAN", "SA4420000001234567891234", 0, "https://www.iban.com/structure",
         "Public IBAN registry worked example for Saudi Arabia (documentation sample)."),
        ("IBAN", "AE460090000000123456789", 0, "https://www.iban.com/structure",
         "Public IBAN registry worked example for the UAE."),
        ("IBAN", "QA54QNBA000000000000693123456", 0, "https://www.iban.com/structure",
         "Public IBAN registry worked example for Qatar."),
        ("IBAN", "KW81CBKU0000000000001234560101", 0, "https://www.iban.com/structure",
         "Public IBAN registry worked example for Kuwait."),
        ("IBAN", "BH02CITI00001077181611", 0, "https://www.iban.com/structure",
         "Public IBAN registry worked example for Bahrain."),
        ("IBAN", "OM040280000012345678901", 0, "https://www.iban.com/structure",
         "Public IBAN registry worked example for Oman."),
        ("IBAN", "SA3915000999103143430001", 0, "https://rulebook.sama.gov.sa/en/printed-iban-account-formats",
         "Saudi Central Bank (SAMA) Rulebook official printed-IBAN worked example."),
    ],
    "zatca_tax_invoice.txt": [
        ("ORGANIZATION", "Bobs Records", 0, "https://zatca.gov.sa/ar/E-Invoicing/SystemsDevelopers/Documents/QRCodeCreation.pdf",
         "Seller name in ZATCA's published QR-code worked example."),
        ("TAX_NUMBER", "310122393500003", 0, "https://zatca.gov.sa/ar/E-Invoicing/SystemsDevelopers/Documents/QRCodeCreation.pdf",
         "Seller VAT number in ZATCA's published QR-code worked example."),
        ("ORGANIZATION", "Bobs Basement Records", 0, "https://zatca.gov.sa/ar/E-Invoicing/SystemsDevelopers/Documents/QRCodeCreation.pdf",
         "Second seller name in the same ZATCA worked example."),
        ("TAX_NUMBER", "100025906700003", 0, "https://zatca.gov.sa/ar/E-Invoicing/SystemsDevelopers/Documents/QRCodeCreation.pdf",
         "Second VAT number in the same ZATCA worked example."),
    ],
    "cr_extract_jarir.txt": [
        ("ORGANIZATION", "Jarir Marketing Company", 0, "https://www.jarir.com/sa-en/about-jarir/company-profile",
         "Legal name on Jarir's public company-profile page."),
        ("COMMERCIAL_REGISTRATION", "1010032264", 0, "https://www.jarir.com/sa-en/about-jarir/company-profile",
         "Jarir CR number published on its company-profile page."),
        ("COMMERCIAL_REGISTRATION", "1010654213", 0, "https://www.jarir.com/sa-en/about-jarir/company-profile",
         "Jarir online (e-commerce) CR number on the same page."),
        ("TAX_NUMBER", "300056289500003", 0, "https://www.jarir.com/sa-en/about-jarir/company-profile",
         "Jarir merchant VAT number on the same page."),
    ],
    "corporate_disclosure_sabic.txt": [
        ("ORGANIZATION", "Saudi Basic Industries Corporation (SABIC)", 0,
         "https://www.sabic.com/en/locations/5604-saudi-arabia-saudi-basic-industries-corporation-hq",
         "Issuer legal name on SABIC's public HQ page."),
        ("ORGANIZATION", "الشركة السعودية للصناعات الأساسية", 0,
         "https://ar.wikipedia.org/wiki/الشركة_السعودية_للصناعات_الأساسية",
         "Arabic legal name of SABIC (Arabic-Wikipedia, public corporate identity)."),
        ("COMMERCIAL_REGISTRATION", "1010010813", 0,
         "https://www.sabic.com/en/Images/SABIC%20Financials%202024_tcm1010-46869.pdf",
         "SABIC CR number as disclosed in its official 2024 financial statements (\"commercial registration No. 1010010813\")."),
        ("TAX_NUMBER", "300000316410003", 0, "https://supplier.sabic.com/SABICVAT.aspx",
         "SABIC Group VAT number published on its supplier VAT-certificate page."),
        ("ADDRESS", "PO Box 5101, Riyadh 11422, Saudi Arabia", 0,
         "https://www.sabic.com/en/locations/5604-saudi-arabia-saudi-basic-industries-corporation-hq",
         "SABIC HQ address on its public locations page."),
        ("PHONE", "+966 (011) 225 8000", 0,
         "https://www.sabic.com/en/locations/5604-saudi-arabia-saudi-basic-industries-corporation-hq",
         "SABIC HQ telephone on its public locations page."),
        ("PHONE", "+966 (011) 225 9000", 0,
         "https://www.sabic.com/en/locations/5604-saudi-arabia-saudi-basic-industries-corporation-hq",
         "SABIC HQ fax on its public locations page."),
    ],
    "university_directory_ksa_uae.txt": [
        ("ORGANIZATION", "King Saud University", 0, "https://ksu.edu.sa/en/Contact-Us",
         "University name on its public Contact-Us page."),
        ("PHONE", "+966 11 467 0000", 0, "https://ksu.edu.sa/en/Contact-Us",
         "KSU general-enquiries phone on its public Contact-Us page."),
        ("EMAIL", "info@ksu.edu.sa", 0, "https://ksu.edu.sa/en/Contact-Us",
         "KSU public email on its Contact-Us page."),
        ("PHONE", "+971 3 701 7111", 0, "https://www.uaeu.ac.ae/en/contact/index.shtml",
         "UAEU international phone on its public Contact page."),
        ("PHONE", "+971 3 713 4343", 0, "https://www.uaeu.ac.ae/en/contact/index.shtml",
         "UAEU fax on its public Contact page."),
        ("EMAIL", "servicedesk@uaeu.ac.ae", 0, "https://www.uaeu.ac.ae/en/contact/index.shtml",
         "UAEU public service-desk email on its Contact page."),
        ("ADDRESS", "United Arab Emirates University, P.O. Box 15551,\n   Sheik Khalifa Bin Zayed St, Asharij, Shiebat Al Oud, Abu Dhabi", 0,
         "https://www.uaeu.ac.ae/en/contact/index.shtml",
         "UAEU public postal address on its Contact page."),
    ],
    "university_contact_gulf.txt": [
        ("PHONE", "(+974) 44033333", 0, "https://www.qu.edu.qa/en-us/about/Pages/contact-us.aspx",
         "Qatar University main call-centre number on its public Contact page."),
        ("EMAIL", "QUMCC@qu.edu.qa", 0, "https://www.qu.edu.qa/en-us/about/Pages/contact-us.aspx",
         "Qatar University public email on its Contact page."),
        ("PHONE", "+973 1743 8888", 0, "https://www.uob.edu.bh/locations/",
         "University of Bahrain phone on its public Locations page."),
        ("PHONE", "+973 1787 6666", 0, "https://www.uob.edu.bh/locations/",
         "University of Bahrain alternate phone on its public Locations page."),
        ("EMAIL", "website@uob.edu.bh", 0, "https://www.uob.edu.bh/locations/",
         "University of Bahrain public email on its Locations page."),
        ("ADDRESS", "University of Bahrain, P.O. Box 32038, Sakhir,\n   Kingdom of Bahrain", 0,
         "https://www.uob.edu.bh/locations/",
         "University of Bahrain public address on its Locations page."),
        ("PHONE", "+965 2498 8888", 0, "https://www.ku.edu.kw/contact-us",
         "Kuwait University phone on its public Contact-Us page."),
        ("EMAIL", "admission@ku.edu.kw", 0, "https://www.ku.edu.kw/contact-us",
         "Kuwait University public admissions email on its Contact-Us page."),
        ("ORGANIZATION", "Sultan Qaboos University", 0, "https://www.squ.edu.om/ccg/Contact-us",
         "Sultan Qaboos University name on its public Contact-us page (Oman)."),
        ("PHONE", "24145989", 0, "https://www.squ.edu.om/ccg/Contact-us",
         "Sultan Qaboos University (Oman) public telephone on its Contact-us page."),
        ("EMAIL", "career@squ.edu.om", 0, "https://www.squ.edu.om/ccg/Contact-us",
         "Sultan Qaboos University public email on its Contact-us page."),
        ("ADDRESS", "Sultan Qaboos University, Al Khoudh, P.O. Box: 50,\n   Postal Code: 123, Sultanate of Oman", 0,
         "https://www.squ.edu.om/ccg/Contact-us",
         "Sultan Qaboos University public address on its Contact-us page (Oman)."),
    ],
    "charity_payment_instructions.txt": [
        ("ORGANIZATION", "Qatar Charity", 0, "https://www.qcharity.org/en/global/zakat/pay-zakat/zakat-bank-transfer",
         "Charity name on its public donation bank-transfer page."),
        ("IBAN", "QA92QIIB000000001111170088070", 0, "https://www.qcharity.org/en/global/zakat/pay-zakat/zakat-bank-transfer",
         "Qatar Charity QIIB donation IBAN (publicly published)."),
        ("IBAN", "QA37QNBA000000000786746207060", 0, "https://www.qcharity.org/en/global/zakat/pay-zakat/zakat-bank-transfer",
         "Qatar Charity QNB donation IBAN (publicly published)."),
        ("IBAN", "QA03QISB000000000108181000018", 0, "https://www.qcharity.org/en/global/zakat/pay-zakat/zakat-bank-transfer",
         "Qatar Charity QIB donation IBAN (publicly published)."),
        ("IBAN", "QA16BRWA000000000200000007515", 0, "https://www.qcharity.org/en/global/zakat/pay-zakat/zakat-bank-transfer",
         "Qatar Charity Barwa Bank donation IBAN (publicly published)."),
    ],
    "arabic_news_bio.txt": [
        ("PERSON", "أحمد حسن زويل", 0, "https://ar.wikipedia.org/wiki/أحمد_زويل",
         "Arabic-Wikipedia name of Nobel laureate Ahmed Zewail (public figure)."),
        ("PERSON", "سعد بن عبد العزيز الراشد", 0, "https://ar.wikipedia.org/wiki/سعد_بن_عبد_العزيز_الراشد",
         "Arabic-Wikipedia name of archaeologist Saad Al-Rashid (public figure)."),
        ("PERSON", "سارة بنت جماز السحيمي", 0,
         "https://annualreport.tadawulgroup.sa/Resources/AnnualReport2022/ar/governance_report/board_of_directors.html",
         "Tadawul annual-report Arabic name of chairperson Sarah Al-Suhaimi."),
        ("PERSON", "بدور بنت سلطان بن محمد القاسمي", 0,
         "https://en.wikipedia.org/wiki/Bodour_bint_Sultan_bin_Mohammed_Al_Qasimi",
         "Wikipedia Arabic name of Sheikha Bodour Al Qasimi (public figure)."),
    ],
    "english_news_bio.txt": [
        ("PERSON", "Ahmed Hassan Zewail", 0, "https://en.wikipedia.org/wiki/Ahmed_Zewail",
         "English-Wikipedia name of Nobel laureate Ahmed Zewail (public figure)."),
        ("ORGANIZATION", "California Institute of Technology", 0, "https://en.wikipedia.org/wiki/Ahmed_Zewail",
         "Institution affiliation in Zewail's public biography."),
        ("PERSON", "Saad Abdulaziz Alrashid", 0, "https://kingfaisalprize.org/professor-saad-abdulaziz-alrashid/",
         "King Faisal Prize laureate page English name of Saad Al-Rashid."),
        ("PERSON", "Sarah Al-Suhaimi", 0, "https://en.wikipedia.org/wiki/Sarah_Al-Suhaimi",
         "English-Wikipedia name of Tadawul chairperson Sarah Al-Suhaimi (public figure)."),
        ("PERSON", "Bodour bint Sultan bin Mohammed Al Qasimi", 0,
         "https://en.wikipedia.org/wiki/Bodour_bint_Sultan_bin_Mohammed_Al_Qasimi",
         "English-Wikipedia name of Sheikha Bodour Al Qasimi (public figure)."),
        ("ORGANIZATION", "American University of Sharjah", 0,
         "https://en.wikipedia.org/wiki/Bodour_bint_Sultan_bin_Mohammed_Al_Qasimi",
         "Institution in Bodour Al Qasimi's public biography."),
    ],
    "kyc_onboarding_form.txt": [
        ("ORGANIZATION", "Saudi Basic Industries Corporation (SABIC)", 0,
         "https://www.sabic.com/en/locations/5604-saudi-arabia-saudi-basic-industries-corporation-hq",
         "SABIC legal name (public)."),
        ("COMMERCIAL_REGISTRATION", "1010010813", 0,
         "https://www.sabic.com/en/Images/SABIC%20Financials%202024_tcm1010-46869.pdf",
         "SABIC CR number from its official 2024 financial statements (public)."),
        ("TAX_NUMBER", "300000316410003", 0, "https://supplier.sabic.com/SABICVAT.aspx",
         "SABIC Group VAT number (public)."),
        ("ADDRESS", "PO Box 5101, Riyadh 11422, Saudi Arabia", 0,
         "https://www.sabic.com/en/locations/5604-saudi-arabia-saudi-basic-industries-corporation-hq",
         "SABIC HQ address (public)."),
        ("PHONE", "+966 (011) 225 8000", 0,
         "https://www.sabic.com/en/locations/5604-saudi-arabia-saudi-basic-industries-corporation-hq",
         "SABIC HQ phone (public)."),
        ("PERSON", "Sarah Al-Suhaimi", 0, "https://en.wikipedia.org/wiki/Sarah_Al-Suhaimi",
         "Public figure name used as authorised-signatory reference."),
        ("IBAN", "SA4420000001234567891234", 0, "https://www.iban.com/structure",
         "Public IBAN registry SA worked example used as settlement IBAN."),
        ("ORGANIZATION", "Jarir Marketing Company", 0, "https://www.jarir.com/sa-en/about-jarir/company-profile",
         "Jarir legal name (public)."),
        ("COMMERCIAL_REGISTRATION", "1010032264", 0, "https://www.jarir.com/sa-en/about-jarir/company-profile",
         "Jarir CR number (public)."),
        ("TAX_NUMBER", "300056289500003", 0, "https://www.jarir.com/sa-en/about-jarir/company-profile",
         "Jarir VAT number (public)."),
        ("IBAN", "AE460090000000123456789", 0, "https://www.iban.com/structure",
         "Public IBAN registry AE worked example used as beneficiary IBAN."),
    ],
    "support_chat_bilingual.txt": [
        ("IBAN", "QA37QNBA000000000786746207060", 0, "https://www.qcharity.org/en/global/zakat/pay-zakat/zakat-bank-transfer",
         "Qatar Charity QNB donation IBAN (public)."),
        ("IBAN", "SA3915000999103143430001", 0, "https://rulebook.sama.gov.sa/en/printed-iban-account-formats",
         "SAMA Rulebook SA worked-example IBAN (public)."),
        ("PHONE", "(+974) 44033333", 0, "https://www.qu.edu.qa/en-us/about/Pages/contact-us.aspx",
         "Qatar University public call-centre number (public)."),
        ("EMAIL", "QUMCC@qu.edu.qa", 0, "https://www.qu.edu.qa/en-us/about/Pages/contact-us.aspx",
         "Qatar University public email (public)."),
        ("PHONE", "+966 11 467 0000", 0, "https://ksu.edu.sa/en/Contact-Us",
         "King Saud University public enquiries number (public)."),
    ],
    "payroll_wps_sheet.txt": [
        ("ORGANIZATION", "Jarir Marketing Company", 0, "https://www.jarir.com/sa-en/about-jarir/company-profile",
         "Jarir legal name (public)."),
        ("COMMERCIAL_REGISTRATION", "1010032264", 0, "https://www.jarir.com/sa-en/about-jarir/company-profile",
         "Jarir CR number (public)."),
        ("TAX_NUMBER", "300056289500003", 0, "https://www.jarir.com/sa-en/about-jarir/company-profile",
         "Jarir VAT number (public)."),
        ("IBAN", "SA4420000001234567891234", 0, "https://www.iban.com/structure",
         "Public IBAN registry SA worked example as employer disbursement IBAN."),
        ("PHONE", "+966 11 467 0000", 0, "https://ksu.edu.sa/en/Contact-Us",
         "Public KSU enquiries number reused as establishment contact."),
        ("IBAN", "BH02CITI00001077181611", 0, "https://www.iban.com/structure",
         "Public IBAN registry BH worked example."),
        ("IBAN", "KW81CBKU0000000000001234560101", 0, "https://www.iban.com/structure",
         "Public IBAN registry KW worked example."),
        ("IBAN", "OM040280000012345678901", 0, "https://www.iban.com/structure",
         "Public IBAN registry OM worked example."),
    ],
    "government_directory_page.txt": [
        ("ORGANIZATION", "Saudi Tadawul Group", 0,
         "https://annualreport.tadawulgroup.sa/Resources/AnnualReport2022/governance_report/board_of_directors.html",
         "Tadawul group name (public annual report)."),
        ("PERSON", "سارة بنت جماز السحيمي", 0,
         "https://annualreport.tadawulgroup.sa/Resources/AnnualReport2022/ar/governance_report/board_of_directors.html",
         "Tadawul Arabic chairperson name (public)."),
        ("PERSON", "Sarah Al-Suhaimi", 0, "https://en.wikipedia.org/wiki/Sarah_Al-Suhaimi",
         "English-Wikipedia name of chairperson (public)."),
        ("ORGANIZATION", "Saudi Basic Industries Corporation (SABIC)", 0,
         "https://www.sabic.com/en/locations/5604-saudi-arabia-saudi-basic-industries-corporation-hq",
         "SABIC legal name (public)."),
        ("ORGANIZATION", "United Arab Emirates University", 0, "https://www.uaeu.ac.ae/en/contact/index.shtml",
         "UAEU name (public)."),
        ("ADDRESS", "United Arab Emirates University, P.O. Box 15551,\n   Sheik Khalifa Bin Zayed St, Asharij, Shiebat Al Oud, Abu Dhabi", 0,
         "https://www.uaeu.ac.ae/en/contact/index.shtml",
         "UAEU public postal address."),
        ("PHONE", "+971 3 701 7111", 0, "https://www.uaeu.ac.ae/en/contact/index.shtml",
         "UAEU public phone."),
        ("ORGANIZATION", "University of Bahrain", 0, "https://www.uob.edu.bh/locations/",
         "University of Bahrain name (public)."),
        ("ADDRESS", "University of Bahrain, P.O. Box 32038, Sakhir,\n   Kingdom of Bahrain", 0,
         "https://www.uob.edu.bh/locations/",
         "University of Bahrain public address."),
        ("EMAIL", "website@uob.edu.bh", 0, "https://www.uob.edu.bh/locations/",
         "University of Bahrain public email."),
        ("ORGANIZATION", "جامعة الملك سعود", 0, "https://ksu.edu.sa/ar/Contact-Us",
         "Arabic-script name of King Saud University on its Arabic Contact-Us page."),
        ("ADDRESS", "جامعة الملك سعود، الرياض، المملكة العربية السعودية", 0,
         "https://ksu.edu.sa/ar/Contact-Us",
         "Arabic-script postal address of King Saud University on its Arabic Contact-Us page."),
    ],
    "passport_specimen_icao.txt": [
        ("PERSON", "ERIKSSON, ANNA MARIA", 0,
         "https://www.icao.int/sites/default/files/publications/DocSeries/9303_p4_cons_en.pdf",
         "ICAO Doc 9303 specimen passport holder (fictional, published example)."),
    ],
    "press_contact_page.txt": [
        ("ORGANIZATION", "Qatar University", 0, "https://www.qu.edu.qa/en-us/about/Pages/contact-us.aspx",
         "Qatar University name (public)."),
        ("PHONE", "(+974) 44033333", 0, "https://www.qu.edu.qa/en-us/about/Pages/contact-us.aspx",
         "Qatar University public call-centre number."),
        ("EMAIL", "QUMCC@qu.edu.qa", 0, "https://www.qu.edu.qa/en-us/about/Pages/contact-us.aspx",
         "Qatar University public email."),
        ("ORGANIZATION", "Kuwait University", 0, "https://www.ku.edu.kw/contact-us",
         "Kuwait University name (public)."),
        ("PHONE", "+965 2498 8888", 0, "https://www.ku.edu.kw/contact-us",
         "Kuwait University public phone."),
        ("EMAIL", "admission@ku.edu.kw", 0, "https://www.ku.edu.kw/contact-us",
         "Kuwait University public admissions email."),
        ("ORGANIZATION", "King Saud University", 0, "https://ksu.edu.sa/en/Contact-Us",
         "King Saud University name (public)."),
        ("PHONE", "+966 11 467 0000", 0, "https://ksu.edu.sa/en/Contact-Us",
         "King Saud University public enquiries number."),
        ("EMAIL", "info@ksu.edu.sa", 0, "https://ksu.edu.sa/en/Contact-Us",
         "King Saud University public email."),
    ],
}


def byte_offset(data: bytes, needle: bytes, occurrence: int) -> int:
    cursor = 0
    for _ in range(occurrence + 1):
        idx = data.find(needle, cursor)
        if idx < 0:
            return -1
        cursor = idx + 1
    return idx


def main() -> int:
    errors = []
    total = 0
    per_kind = {}
    manifest = {}  # filename -> list of (kind, value, url, note)

    for fname, specs in SPECS.items():
        path = os.path.join(CORPUS, fname)
        if not os.path.exists(path):
            errors.append(f"{fname}: corpus file missing")
            continue
        data = open(path, "rb").read()
        gold_path = os.path.join(GOLD, os.path.splitext(fname)[0] + ".jsonl")
        lines = []
        manifest[fname] = []
        for kind, value, occ, url, note in specs:
            needle = value.encode("utf-8")
            start = byte_offset(data, needle, occ)
            if start < 0:
                errors.append(f"{fname}: NOT FOUND occ={occ}: {value!r}")
                continue
            end = start + len(needle)
            sliced = data[start:end].decode("utf-8")
            if sliced != value:
                errors.append(f"{fname}: ROUND-TRIP FAIL {value!r} != {sliced!r}")
                continue
            if kind == "IBAN":
                compact = value.replace(" ", "")
                if iban_mod97(compact[4:] + compact[:4]) != 1:
                    errors.append(f"{fname}: IBAN MOD-97 FAIL {value!r}")
                    continue
            lines.append(json.dumps({
                "file": fname, "start": start, "end": end,
                "kind": kind, "text": value, "confidence_floor": FLOOR,
            }, ensure_ascii=False))
            per_kind[kind] = per_kind.get(kind, 0) + 1
            total += 1
            manifest[fname].append((kind, value, url, note))
        with open(gold_path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + ("\n" if lines else ""))

    print(f"Wrote {total} spans across {len(SPECS)} fixtures.")
    print("Per-kind counts:")
    for k in sorted(per_kind):
        print(f"  {k}: {per_kind[k]}")
    if errors:
        print("\nERRORS:")
        for e in errors:
            print("  " + e)
        return 1
    print("\nAll spans verified: round-trip OK, IBAN MOD-97 OK.")

    # Emit README manifest from the same structure.
    write_readme(manifest, per_kind, total)
    return 0


def write_readme(manifest, per_kind, total):
    out = [
        "# tests/eval/real — REAL Arabic/GCC PII evaluation corpus",
        "",
        "This corpus is **ground truth**, assembled from publicly-disclosed",
        "sources. Every labeled span is a real, intentionally-published value",
        "(or an official published documentation specimen). It is independent",
        "of any detector code: values were chosen only because they are real",
        "and publicly disclosed, never because a regex would or would not match.",
        "",
        "Documents are realistic GCC scaffolds composed around individually-",
        "sourced real values. No real linkage between a named person and a",
        "specific person and IBAN is asserted; each span stands on its own source.",
        "",
        "Gold format (UTF-8 **byte** offsets), one span per line in",
        "`gold/<name>.jsonl`:",
        "",
        '```',
        '{"file":"<name>.txt","start":N,"end":M,"kind":"KIND","text":"...","confidence_floor":0.85}',
        '```',
        "",
        "Regenerate & verify (round-trip + IBAN MOD-97):",
        "",
        "```",
        "python3 tests/eval/real/build_gold.py",
        "```",
        "",
        f"Total labeled spans: {total}. Per-kind counts:",
        "",
    ]
    for k in sorted(per_kind):
        out.append(f"- {k}: {per_kind[k]}")
    out.append("")
    out.append("## Source manifest (per fixture, per span)")
    out.append("")
    for fname in SPECS:
        rows = manifest.get(fname, [])
        if not rows:
            continue
        out.append(f"### {fname}")
        out.append("")
        for kind, value, url, note in rows:
            display = value.replace("\n", " ")
            out.append(f"- `{kind}` `{display}` — {note} Source: {url}")
        out.append("")
    out.append("## Coverage notes — scarce / unfilled kinds")
    out.append("")
    out.append("- `NATIONAL_ID` (0 spans, unfilled): No clean, individually-")
    out.append("  published GCC national-ID number could be found from a legitimate")
    out.append("  intentional-disclosure source. Real national-ID numbers belong to")
    out.append("  private individuals (forbidden), and government pages publish only")
    out.append("  the *format* (e.g. the Emirates ID shape `784-YYYY-XXXXXXX-X`), not")
    out.append("  a clean specimen value. Per the task, this kind is reported as")
    out.append("  not-fillable rather than synthesized.")
    out.append("")
    readme_path = os.path.join(HERE, "README.md")
    with open(readme_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(out))
    print(f"Wrote manifest: {readme_path}")


if __name__ == "__main__":
    sys.exit(main())
