"""Column-aware CSV redaction: header classification + round-trip."""

from __future__ import annotations

import csv
import io

from apii import config, default_pipeline
from apii.anonymizer import Anonymizer
from apii.csvcols import column_kind, redact_columns
from apii.types import EntityKind


def test_column_classification_real_headers():
    K = EntityKind
    cases = {
        # PII → kind
        "First Name": K.PERSON, "Last Name": K.PERSON, "Lead Owner": K.PERSON,
        "arabicName": K.PERSON, "name": K.PERSON, "Converted Contact": K.PERSON,
        "Company": K.ORGANIZATION, "Business Name": K.ORGANIZATION,
        "اسم الشركة": K.ORGANIZATION, "supplierName": K.ORGANIZATION,
        "Company Name for Emails": K.ORGANIZATION,           # name, not an email
        "Email": K.EMAIL, "Company Email": K.EMAIL, "Descision Maker - Email": K.EMAIL,
        "Phone": K.PHONE, "Mobile Phone": K.PHONE, "Company Phone": K.PHONE,
        "Whatsapp Magic url": K.PHONE,
        "City": K.ADDRESS, "Street": K.ADDRESS, "Company City": K.ADDRESS,
        "Company Country": K.ADDRESS,
        # NOT PII → None
        "Email Status": None, "Email Bounced": None,
        "Primary Email Verification Source": None,
        "Ad Name": None, "Ad Campaign Name": None, "AdGroup Name": None,
        "tender1_name": None, "Facebook Ad Name": None,
        "Company Type": None, "Company age (in years)": None,
        "Account.id": None, "Lead Owner.id": None,
        "Created Time": None, "Is Converted": None, "Title": None,
    }
    for header, expect in cases.items():
        assert column_kind(header) is expect, (header, column_kind(header), expect)


def test_redact_columns_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("APII_HOME", str(tmp_path))
    secret = config.load_or_create_secret()
    anon = Anonymizer.from_records(secret, "t", [], pipeline=default_pipeline(enable_ner=False))

    src = ("First Name,Email,Phone,Company,Lead Status,Account.id\n"
           "محمد,omar@aajil.sa,0501234567,شركة الركائز,New Lead,zcrm_99\n").encode()
    red = redact_columns(src, anon)
    rows = list(csv.reader(io.StringIO(red.decode())))
    hdr, data = rows[0], rows[1]
    # header untouched
    assert hdr == ["First Name", "Email", "Phone", "Company", "Lead Status", "Account.id"]
    # PII tokenized
    assert data[0].startswith("PERSON_") and data[1].startswith("EMAIL_")
    assert data[2].startswith("PHONE_") and data[3].startswith("ORG_")
    # metadata preserved
    assert data[4] == "New Lead" and data[5] == "zcrm_99"
    # reversible
    assert anon.deanonymize(data[0]) == "محمد"
    assert anon.deanonymize(data[1]) == "omar@aajil.sa"
