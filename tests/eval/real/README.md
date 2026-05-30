# tests/eval/real — REAL Arabic/GCC PII evaluation corpus

This corpus is **ground truth**, assembled from publicly-disclosed
sources. Every labeled span is a real, intentionally-published value
(or an official published documentation specimen). It is independent
of any detector code: values were chosen only because they are real
and publicly disclosed, never because a regex would or would not match.

Documents are realistic GCC scaffolds composed around individually-
sourced real values. No real linkage between a named person and a
specific person and IBAN is asserted; each span stands on its own source.

Gold format (UTF-8 **byte** offsets), one span per line in
`gold/<name>.jsonl`:

```
{"file":"<name>.txt","start":N,"end":M,"kind":"KIND","text":"...","confidence_floor":0.85}
```

Regenerate & verify (round-trip + IBAN MOD-97):

```
python3 tests/eval/real/build_gold.py
```

Total labeled spans: 102. Per-kind counts:

- ADDRESS: 8
- COMMERCIAL_REGISTRATION: 6
- EMAIL: 11
- IBAN: 19
- ORGANIZATION: 21
- PERSON: 12
- PHONE: 18
- TAX_NUMBER: 7

## Source manifest (per fixture, per span)

### iban_calculator_faq.txt

- `IBAN` `SA4420000001234567891234` — Public IBAN registry worked example for Saudi Arabia (documentation sample). Source: https://www.iban.com/structure
- `IBAN` `AE460090000000123456789` — Public IBAN registry worked example for the UAE. Source: https://www.iban.com/structure
- `IBAN` `QA54QNBA000000000000693123456` — Public IBAN registry worked example for Qatar. Source: https://www.iban.com/structure
- `IBAN` `KW81CBKU0000000000001234560101` — Public IBAN registry worked example for Kuwait. Source: https://www.iban.com/structure
- `IBAN` `BH02CITI00001077181611` — Public IBAN registry worked example for Bahrain. Source: https://www.iban.com/structure
- `IBAN` `OM040280000012345678901` — Public IBAN registry worked example for Oman. Source: https://www.iban.com/structure
- `IBAN` `SA3915000999103143430001` — Saudi Central Bank (SAMA) Rulebook official printed-IBAN worked example. Source: https://rulebook.sama.gov.sa/en/printed-iban-account-formats

### zatca_tax_invoice.txt

- `ORGANIZATION` `Bobs Records` — Seller name in ZATCA's published QR-code worked example. Source: https://zatca.gov.sa/ar/E-Invoicing/SystemsDevelopers/Documents/QRCodeCreation.pdf
- `TAX_NUMBER` `310122393500003` — Seller VAT number in ZATCA's published QR-code worked example. Source: https://zatca.gov.sa/ar/E-Invoicing/SystemsDevelopers/Documents/QRCodeCreation.pdf
- `ORGANIZATION` `Bobs Basement Records` — Second seller name in the same ZATCA worked example. Source: https://zatca.gov.sa/ar/E-Invoicing/SystemsDevelopers/Documents/QRCodeCreation.pdf
- `TAX_NUMBER` `100025906700003` — Second VAT number in the same ZATCA worked example. Source: https://zatca.gov.sa/ar/E-Invoicing/SystemsDevelopers/Documents/QRCodeCreation.pdf

### cr_extract_jarir.txt

- `ORGANIZATION` `Jarir Marketing Company` — Legal name on Jarir's public company-profile page. Source: https://www.jarir.com/sa-en/about-jarir/company-profile
- `COMMERCIAL_REGISTRATION` `1010032264` — Jarir CR number published on its company-profile page. Source: https://www.jarir.com/sa-en/about-jarir/company-profile
- `COMMERCIAL_REGISTRATION` `1010654213` — Jarir online (e-commerce) CR number on the same page. Source: https://www.jarir.com/sa-en/about-jarir/company-profile
- `TAX_NUMBER` `300056289500003` — Jarir merchant VAT number on the same page. Source: https://www.jarir.com/sa-en/about-jarir/company-profile

### corporate_disclosure_sabic.txt

- `ORGANIZATION` `Saudi Basic Industries Corporation (SABIC)` — Issuer legal name on SABIC's public HQ page. Source: https://www.sabic.com/en/locations/5604-saudi-arabia-saudi-basic-industries-corporation-hq
- `ORGANIZATION` `الشركة السعودية للصناعات الأساسية` — Arabic legal name of SABIC (Arabic-Wikipedia, public corporate identity). Source: https://ar.wikipedia.org/wiki/الشركة_السعودية_للصناعات_الأساسية
- `COMMERCIAL_REGISTRATION` `1010010813` — SABIC CR number as disclosed in its official 2024 financial statements ("commercial registration No. 1010010813"). Source: https://www.sabic.com/en/Images/SABIC%20Financials%202024_tcm1010-46869.pdf
- `TAX_NUMBER` `300000316410003` — SABIC Group VAT number published on its supplier VAT-certificate page. Source: https://supplier.sabic.com/SABICVAT.aspx
- `ADDRESS` `PO Box 5101, Riyadh 11422, Saudi Arabia` — SABIC HQ address on its public locations page. Source: https://www.sabic.com/en/locations/5604-saudi-arabia-saudi-basic-industries-corporation-hq
- `PHONE` `+966 (011) 225 8000` — SABIC HQ telephone on its public locations page. Source: https://www.sabic.com/en/locations/5604-saudi-arabia-saudi-basic-industries-corporation-hq
- `PHONE` `+966 (011) 225 9000` — SABIC HQ fax on its public locations page. Source: https://www.sabic.com/en/locations/5604-saudi-arabia-saudi-basic-industries-corporation-hq

### university_directory_ksa_uae.txt

- `ORGANIZATION` `King Saud University` — University name on its public Contact-Us page. Source: https://ksu.edu.sa/en/Contact-Us
- `PHONE` `+966 11 467 0000` — KSU general-enquiries phone on its public Contact-Us page. Source: https://ksu.edu.sa/en/Contact-Us
- `EMAIL` `info@ksu.edu.sa` — KSU public email on its Contact-Us page. Source: https://ksu.edu.sa/en/Contact-Us
- `PHONE` `+971 3 701 7111` — UAEU international phone on its public Contact page. Source: https://www.uaeu.ac.ae/en/contact/index.shtml
- `PHONE` `+971 3 713 4343` — UAEU fax on its public Contact page. Source: https://www.uaeu.ac.ae/en/contact/index.shtml
- `EMAIL` `servicedesk@uaeu.ac.ae` — UAEU public service-desk email on its Contact page. Source: https://www.uaeu.ac.ae/en/contact/index.shtml
- `ADDRESS` `United Arab Emirates University, P.O. Box 15551,    Sheik Khalifa Bin Zayed St, Asharij, Shiebat Al Oud, Abu Dhabi` — UAEU public postal address on its Contact page. Source: https://www.uaeu.ac.ae/en/contact/index.shtml

### university_contact_gulf.txt

- `PHONE` `(+974) 44033333` — Qatar University main call-centre number on its public Contact page. Source: https://www.qu.edu.qa/en-us/about/Pages/contact-us.aspx
- `EMAIL` `QUMCC@qu.edu.qa` — Qatar University public email on its Contact page. Source: https://www.qu.edu.qa/en-us/about/Pages/contact-us.aspx
- `PHONE` `+973 1743 8888` — University of Bahrain phone on its public Locations page. Source: https://www.uob.edu.bh/locations/
- `PHONE` `+973 1787 6666` — University of Bahrain alternate phone on its public Locations page. Source: https://www.uob.edu.bh/locations/
- `EMAIL` `website@uob.edu.bh` — University of Bahrain public email on its Locations page. Source: https://www.uob.edu.bh/locations/
- `ADDRESS` `University of Bahrain, P.O. Box 32038, Sakhir,    Kingdom of Bahrain` — University of Bahrain public address on its Locations page. Source: https://www.uob.edu.bh/locations/
- `PHONE` `+965 2498 8888` — Kuwait University phone on its public Contact-Us page. Source: https://www.ku.edu.kw/contact-us
- `EMAIL` `admission@ku.edu.kw` — Kuwait University public admissions email on its Contact-Us page. Source: https://www.ku.edu.kw/contact-us
- `ORGANIZATION` `Sultan Qaboos University` — Sultan Qaboos University name on its public Contact-us page (Oman). Source: https://www.squ.edu.om/ccg/Contact-us
- `PHONE` `24145989` — Sultan Qaboos University (Oman) public telephone on its Contact-us page. Source: https://www.squ.edu.om/ccg/Contact-us
- `EMAIL` `career@squ.edu.om` — Sultan Qaboos University public email on its Contact-us page. Source: https://www.squ.edu.om/ccg/Contact-us
- `ADDRESS` `Sultan Qaboos University, Al Khoudh, P.O. Box: 50,    Postal Code: 123, Sultanate of Oman` — Sultan Qaboos University public address on its Contact-us page (Oman). Source: https://www.squ.edu.om/ccg/Contact-us

### charity_payment_instructions.txt

- `ORGANIZATION` `Qatar Charity` — Charity name on its public donation bank-transfer page. Source: https://www.qcharity.org/en/global/zakat/pay-zakat/zakat-bank-transfer
- `IBAN` `QA92QIIB000000001111170088070` — Qatar Charity QIIB donation IBAN (publicly published). Source: https://www.qcharity.org/en/global/zakat/pay-zakat/zakat-bank-transfer
- `IBAN` `QA37QNBA000000000786746207060` — Qatar Charity QNB donation IBAN (publicly published). Source: https://www.qcharity.org/en/global/zakat/pay-zakat/zakat-bank-transfer
- `IBAN` `QA03QISB000000000108181000018` — Qatar Charity QIB donation IBAN (publicly published). Source: https://www.qcharity.org/en/global/zakat/pay-zakat/zakat-bank-transfer
- `IBAN` `QA16BRWA000000000200000007515` — Qatar Charity Barwa Bank donation IBAN (publicly published). Source: https://www.qcharity.org/en/global/zakat/pay-zakat/zakat-bank-transfer

### arabic_news_bio.txt

- `PERSON` `أحمد حسن زويل` — Arabic-Wikipedia name of Nobel laureate Ahmed Zewail (public figure). Source: https://ar.wikipedia.org/wiki/أحمد_زويل
- `PERSON` `سعد بن عبد العزيز الراشد` — Arabic-Wikipedia name of archaeologist Saad Al-Rashid (public figure). Source: https://ar.wikipedia.org/wiki/سعد_بن_عبد_العزيز_الراشد
- `PERSON` `سارة بنت جماز السحيمي` — Tadawul annual-report Arabic name of chairperson Sarah Al-Suhaimi. Source: https://annualreport.tadawulgroup.sa/Resources/AnnualReport2022/ar/governance_report/board_of_directors.html
- `PERSON` `بدور بنت سلطان بن محمد القاسمي` — Wikipedia Arabic name of Sheikha Bodour Al Qasimi (public figure). Source: https://en.wikipedia.org/wiki/Bodour_bint_Sultan_bin_Mohammed_Al_Qasimi

### english_news_bio.txt

- `PERSON` `Ahmed Hassan Zewail` — English-Wikipedia name of Nobel laureate Ahmed Zewail (public figure). Source: https://en.wikipedia.org/wiki/Ahmed_Zewail
- `ORGANIZATION` `California Institute of Technology` — Institution affiliation in Zewail's public biography. Source: https://en.wikipedia.org/wiki/Ahmed_Zewail
- `PERSON` `Saad Abdulaziz Alrashid` — King Faisal Prize laureate page English name of Saad Al-Rashid. Source: https://kingfaisalprize.org/professor-saad-abdulaziz-alrashid/
- `PERSON` `Sarah Al-Suhaimi` — English-Wikipedia name of Tadawul chairperson Sarah Al-Suhaimi (public figure). Source: https://en.wikipedia.org/wiki/Sarah_Al-Suhaimi
- `PERSON` `Bodour bint Sultan bin Mohammed Al Qasimi` — English-Wikipedia name of Sheikha Bodour Al Qasimi (public figure). Source: https://en.wikipedia.org/wiki/Bodour_bint_Sultan_bin_Mohammed_Al_Qasimi
- `ORGANIZATION` `American University of Sharjah` — Institution in Bodour Al Qasimi's public biography. Source: https://en.wikipedia.org/wiki/Bodour_bint_Sultan_bin_Mohammed_Al_Qasimi

### kyc_onboarding_form.txt

- `ORGANIZATION` `Saudi Basic Industries Corporation (SABIC)` — SABIC legal name (public). Source: https://www.sabic.com/en/locations/5604-saudi-arabia-saudi-basic-industries-corporation-hq
- `COMMERCIAL_REGISTRATION` `1010010813` — SABIC CR number from its official 2024 financial statements (public). Source: https://www.sabic.com/en/Images/SABIC%20Financials%202024_tcm1010-46869.pdf
- `TAX_NUMBER` `300000316410003` — SABIC Group VAT number (public). Source: https://supplier.sabic.com/SABICVAT.aspx
- `ADDRESS` `PO Box 5101, Riyadh 11422, Saudi Arabia` — SABIC HQ address (public). Source: https://www.sabic.com/en/locations/5604-saudi-arabia-saudi-basic-industries-corporation-hq
- `PHONE` `+966 (011) 225 8000` — SABIC HQ phone (public). Source: https://www.sabic.com/en/locations/5604-saudi-arabia-saudi-basic-industries-corporation-hq
- `PERSON` `Sarah Al-Suhaimi` — Public figure name used as authorised-signatory reference. Source: https://en.wikipedia.org/wiki/Sarah_Al-Suhaimi
- `IBAN` `SA4420000001234567891234` — Public IBAN registry SA worked example used as settlement IBAN. Source: https://www.iban.com/structure
- `ORGANIZATION` `Jarir Marketing Company` — Jarir legal name (public). Source: https://www.jarir.com/sa-en/about-jarir/company-profile
- `COMMERCIAL_REGISTRATION` `1010032264` — Jarir CR number (public). Source: https://www.jarir.com/sa-en/about-jarir/company-profile
- `TAX_NUMBER` `300056289500003` — Jarir VAT number (public). Source: https://www.jarir.com/sa-en/about-jarir/company-profile
- `IBAN` `AE460090000000123456789` — Public IBAN registry AE worked example used as beneficiary IBAN. Source: https://www.iban.com/structure

### support_chat_bilingual.txt

- `IBAN` `QA37QNBA000000000786746207060` — Qatar Charity QNB donation IBAN (public). Source: https://www.qcharity.org/en/global/zakat/pay-zakat/zakat-bank-transfer
- `IBAN` `SA3915000999103143430001` — SAMA Rulebook SA worked-example IBAN (public). Source: https://rulebook.sama.gov.sa/en/printed-iban-account-formats
- `PHONE` `(+974) 44033333` — Qatar University public call-centre number (public). Source: https://www.qu.edu.qa/en-us/about/Pages/contact-us.aspx
- `EMAIL` `QUMCC@qu.edu.qa` — Qatar University public email (public). Source: https://www.qu.edu.qa/en-us/about/Pages/contact-us.aspx
- `PHONE` `+966 11 467 0000` — King Saud University public enquiries number (public). Source: https://ksu.edu.sa/en/Contact-Us

### payroll_wps_sheet.txt

- `ORGANIZATION` `Jarir Marketing Company` — Jarir legal name (public). Source: https://www.jarir.com/sa-en/about-jarir/company-profile
- `COMMERCIAL_REGISTRATION` `1010032264` — Jarir CR number (public). Source: https://www.jarir.com/sa-en/about-jarir/company-profile
- `TAX_NUMBER` `300056289500003` — Jarir VAT number (public). Source: https://www.jarir.com/sa-en/about-jarir/company-profile
- `IBAN` `SA4420000001234567891234` — Public IBAN registry SA worked example as employer disbursement IBAN. Source: https://www.iban.com/structure
- `PHONE` `+966 11 467 0000` — Public KSU enquiries number reused as establishment contact. Source: https://ksu.edu.sa/en/Contact-Us
- `IBAN` `BH02CITI00001077181611` — Public IBAN registry BH worked example. Source: https://www.iban.com/structure
- `IBAN` `KW81CBKU0000000000001234560101` — Public IBAN registry KW worked example. Source: https://www.iban.com/structure
- `IBAN` `OM040280000012345678901` — Public IBAN registry OM worked example. Source: https://www.iban.com/structure

### government_directory_page.txt

- `ORGANIZATION` `Saudi Tadawul Group` — Tadawul group name (public annual report). Source: https://annualreport.tadawulgroup.sa/Resources/AnnualReport2022/governance_report/board_of_directors.html
- `PERSON` `سارة بنت جماز السحيمي` — Tadawul Arabic chairperson name (public). Source: https://annualreport.tadawulgroup.sa/Resources/AnnualReport2022/ar/governance_report/board_of_directors.html
- `PERSON` `Sarah Al-Suhaimi` — English-Wikipedia name of chairperson (public). Source: https://en.wikipedia.org/wiki/Sarah_Al-Suhaimi
- `ORGANIZATION` `Saudi Basic Industries Corporation (SABIC)` — SABIC legal name (public). Source: https://www.sabic.com/en/locations/5604-saudi-arabia-saudi-basic-industries-corporation-hq
- `ORGANIZATION` `United Arab Emirates University` — UAEU name (public). Source: https://www.uaeu.ac.ae/en/contact/index.shtml
- `ADDRESS` `United Arab Emirates University, P.O. Box 15551,    Sheik Khalifa Bin Zayed St, Asharij, Shiebat Al Oud, Abu Dhabi` — UAEU public postal address. Source: https://www.uaeu.ac.ae/en/contact/index.shtml
- `PHONE` `+971 3 701 7111` — UAEU public phone. Source: https://www.uaeu.ac.ae/en/contact/index.shtml
- `ORGANIZATION` `University of Bahrain` — University of Bahrain name (public). Source: https://www.uob.edu.bh/locations/
- `ADDRESS` `University of Bahrain, P.O. Box 32038, Sakhir,    Kingdom of Bahrain` — University of Bahrain public address. Source: https://www.uob.edu.bh/locations/
- `EMAIL` `website@uob.edu.bh` — University of Bahrain public email. Source: https://www.uob.edu.bh/locations/
- `ORGANIZATION` `جامعة الملك سعود` — Arabic-script name of King Saud University on its Arabic Contact-Us page. Source: https://ksu.edu.sa/ar/Contact-Us
- `ADDRESS` `جامعة الملك سعود، الرياض، المملكة العربية السعودية` — Arabic-script postal address of King Saud University on its Arabic Contact-Us page. Source: https://ksu.edu.sa/ar/Contact-Us

### passport_specimen_icao.txt

- `PERSON` `ERIKSSON, ANNA MARIA` — ICAO Doc 9303 specimen passport holder (fictional, published example). Source: https://www.icao.int/sites/default/files/publications/DocSeries/9303_p4_cons_en.pdf

### press_contact_page.txt

- `ORGANIZATION` `Qatar University` — Qatar University name (public). Source: https://www.qu.edu.qa/en-us/about/Pages/contact-us.aspx
- `PHONE` `(+974) 44033333` — Qatar University public call-centre number. Source: https://www.qu.edu.qa/en-us/about/Pages/contact-us.aspx
- `EMAIL` `QUMCC@qu.edu.qa` — Qatar University public email. Source: https://www.qu.edu.qa/en-us/about/Pages/contact-us.aspx
- `ORGANIZATION` `Kuwait University` — Kuwait University name (public). Source: https://www.ku.edu.kw/contact-us
- `PHONE` `+965 2498 8888` — Kuwait University public phone. Source: https://www.ku.edu.kw/contact-us
- `EMAIL` `admission@ku.edu.kw` — Kuwait University public admissions email. Source: https://www.ku.edu.kw/contact-us
- `ORGANIZATION` `King Saud University` — King Saud University name (public). Source: https://ksu.edu.sa/en/Contact-Us
- `PHONE` `+966 11 467 0000` — King Saud University public enquiries number. Source: https://ksu.edu.sa/en/Contact-Us
- `EMAIL` `info@ksu.edu.sa` — King Saud University public email. Source: https://ksu.edu.sa/en/Contact-Us

## Coverage notes — scarce / unfilled kinds

- `NATIONAL_ID` (0 spans, unfilled): No clean, individually-
  published GCC national-ID number could be found from a legitimate
  intentional-disclosure source. Real national-ID numbers belong to
  private individuals (forbidden), and government pages publish only
  the *format* (e.g. the Emirates ID shape `784-YYYY-XXXXXXX-X`), not
  a clean specimen value. Per the task, this kind is reported as
  not-fillable rather than synthesized.
