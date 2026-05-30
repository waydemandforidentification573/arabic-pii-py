# tests/eval/real_bulk — BULK real Arabic/GCC PII evaluation corpus

The large sibling of `tests/eval/real`. Where that set hand-curates
~102 spans into multi-entity GCC documents, this set holds **1238**
spans mechanically built from harvested real public values — one fixture
file per harvest slice. It is **ground truth, not synthetic**: every
value is a real, intentionally-published value or a documented
validator test-vector / official specimen. Values were chosen only
because they are real + public, never because a regex would match.

It lives in its OWN root (separate `corpus/` + `gold/`) so the curated
set's tight recall pins stay calibrated to that set. Recall on this
broader, harder distribution is pinned **honestly** (and lower for the
label-cued kinds) in `tests/python/test_real_bulk_corpus.py`.

Gold format (UTF-8 **byte** offsets), one span per line in
`gold/<slice>.jsonl` — identical schema to the curated set:

```
{"file":"bulk_<slice>.txt","start":N,"end":M,"kind":"KIND","text":"...","confidence_floor":0.85}
```

Offsets are computed FROM THE BYTES (never hand-authored); every span is
round-trip-checked on write and IBANs are MOD-97-gated. Regenerate:

```
python3 tests/eval/real_bulk/build_bulk_gold.py   # reads /tmp/apii_gold_harvest
python3 tests/eval/real/verify_gold.py            # verifies real + real_bulk
```

Total labeled spans: 1238 across 23 fixtures. Per-kind:

- ADDRESS: 120
- COMMERCIAL_REGISTRATION: 92
- EMAIL: 163
- IBAN: 145
- NATIONAL_ID: 22
- ORGANIZATION: 259
- PERSON: 182
- PHONE: 204
- TAX_NUMBER: 51

## Provenance — source domains per kind

(Full per-page URLs are in the harvest records; the published
sentence carrying each value is preserved verbatim in the fixture.)

- **ADDRESS**: ambriad.esteri.it, anwaar.squ.edu.om, ar.wikipedia.org, bahrainbourse.com, bhck.edu.kw, bsf.sa, cams.ksu.edu.sa, cap.ksu.edu.sa, catalog.alfaisal.edu, ccis.ksu.edu.sa, ceducation.ku.ac.ae, cep.kfupm.edu.sa, chss.ksu.edu.sa, clps.ksu.edu.sa, engineering.ksu.edu.sa, imsiu-cs.edupage.org, iq.com.qa, jeddah-cg.mfa.gov.tr, jis.ksu.edu.sa, jnsm.qu.edu.sa, kauj.researchcommons.org, mec.edu.om, med.ku.edu.kw, pakistaninksa.com, ps.ksu.edu.sa, pur.ku.edu.kw, qatar-weill.cornell.edu, rib.bankalbilad.com, riyadh-emb.mfa.gov.tr, saudiarabia.diplomatie.belgium.be, saudiarabien.diplo.de, sciences.ksu.edu.sa, snbcapital.com, www.aaicu.org, www.agu.edu.bh, www.ahlia.edu.bh, www.ajman.ac.ae, www.alahli.com, www.alinma.com, www.au.edu.kw, www.aud.edu, www.auk.edu.kw, www.aus.edu, www.bahrainchamber.bh, www.bankmuscat.om, www.bibf.com, www.bits-pilani.ac.in, www.boursakuwait.com.kw, www.cbb.gov.bh, www.cbk.gov.kw, www.dah.edu.sa, www.du.edu.om, www.gov.uk, www.international.gc.ca, www.kaust.edu.sa, www.kfh.com, www.kisr.edu.kw, www.ku.ac.ae, www.maaden.com, www.mobily.com.sa, www.nbk.com, www.netherlandsandyou.nl, www.polytechnic.bh, www.qatar.cmu.edu, www.qatar.northwestern.edu, www.qatar.tamu.edu, www.qatarenergylng.qa, www.qu.edu.qa, www.qu.edu.sa, www.riyadbank.com, www.ruw.edu.bh, www.sabic.com, www.se.com.sa, www.sharjah.ac.ae, www.squ.edu.om, www.stc.com, www.su.edu.om, www.swedenabroad.se, www.tadawulgroup.sa, www.uaeu.ac.ae, www.udst.edu.qa, www.uj.edu.sa, www.unizwa.edu.om, www.utas.edu.om, www.utb.edu.bh, www.zu.ac.ae
- **COMMERCIAL_REGISTRATION**: cma.gov.sa, retal.com.sa, solutions.com.sa
- **EMAIL**: annualreport.tadawulgroup.sa, cap.ksu.edu.sa, ccis.ksu.edu.sa, cis.ku.edu.kw, cls.ku.edu.kw, do.ku.edu.kw, education.ksu.edu.sa, faculty.psau.edu.sa, gsd.ku.edu.kw, iq.com.qa, ir.omantel.om, kicls.ku.edu.kw, ksu.edu.sa, law.uob.edu.bh, math.sci.kuniv.edu.kw, medicine.ksu.edu.sa, my.saudiembassy.sa, pharmacy.ksu.edu.sa, saudicement.com.sa, science.uob.edu.bh, sciences.ksu.edu.sa, snbcapital.com, sr.edu.sa, units.imamu.edu.sa, www.adu.ac.ae, www.alahli.com, www.albasmelter.com, www.alinma.com, www.almarai.com, www.bankalbilad.com.sa, www.bankmuscat.om, www.boursakuwait.com.kw, www.cud.ac.ae, www.dpworld.com, www.kfupm.edu.sa, www.kilaw.edu.kw, www.ku.ac.ae, www.ku.edu.kw, www.maaden.com.sa, www.mobily.com.sa, www.mofa.gov.sa, www.moh.gov.sa, www.omantel.om, www.ooredoo.om, www.petrorabigh.com, www.qatarenergy.qa, www.qf.org.qa, www.qu.edu.qa, www.qu.edu.sa, www.riyadbank.com, www.sab.com, www.sabic.com, www.savola.com, www.squ.edu.om, www.stc.com, www.uae-embassy.org, www.uaeu.ac.ae, www.ubt.edu.sa, www.yansab.com.sa
- **IBAN**: aljalilafoundation.ae, alnajat.org.kw, beitalkhair.org, cbo.gov.om, dohaacademy.sch.qa, khf-kwt.com, my.qatar.northwestern.edu, reliefweb.int, rulebook.sama.gov.sa, tbhf.ae, thepeninsulaqatar.com, webmaster.qis.org, wise.com, www.acsdoha.school, www.aud.edu, www.bisb.com, www.cbb.gov.bh, www.cmu.edu, www.e.gov.kw, www.emiratesairlinefoundation.org, www.iban.com, www.islqatar.org, www.kacch.org, www.khaleejtimes.com, www.qatar.georgetown.edu, www.qcb.gov.qa, www.qcharity.org, www.remitly.com, www.rit.edu, www.sharjah.ac.ae, www.xtransfer.com, www.zakathouse.org.kw, yallagive.com
- **NATIONAL_ID**: designsystem.gov.ae, dubaivisitsvisa.com, github.com, qatarvisainfo.com, virtuzone.com, www.dohaguides.com
- **ORGANIZATION**: ar.wikipedia.org, en.wikipedia.org, www.ithmaarbank.com
- **PERSON**: ar.wikipedia.org, en.wikipedia.org
- **PHONE**: bahrainbourse.com, bas.com.bh, cams.ksu.edu.sa, cep.kfupm.edu.sa, cfas.ksu.edu.sa, cpa.gov.om, dad.kfupm.edu.sa, doha-emb.mfa.gov.tr, education.ksu.edu.sa, engineering.ksu.edu.sa, gsd.ku.edu.kw, hr.kfupm.edu.sa, kuwaitairways.com, la.ku.edu.kw, mofa.gov.pk, qatar.diplomatie.belgium.be, qm.org.qa, ro.ksu.edu.sa, sciences.ksu.edu.sa, www.aus.edu, www.bankboubyan.com, www.bbkonline.com, www.bh.kfh.com, www.bisb.com, www.boursakuwait.com.kw, www.cbo.gov.om, www.e-gulfbank.com, www.fm.gov.om, www.gulfairgroup.bh, www.gutech.edu.om, www.hamad.qa, www.indianembassyqatar.gov.in, www.kfh.com, www.kfupm.edu.sa, www.kockw.com, www.kotc.com.kw, www.kpc.com.kw, www.krcs.org.kw, www.ku.ac.ae, www.kufpec.com, www.kw.zain.com, www.mofa.gov.sa, www.moh.gov.om, www.nbk.com, www.nbkwealth.com, www.netherlandsandyou.nl, www.ooredoo.com.kw, www.polytechnic.bh, www.qatar.northwestern.edu, www.qatar.tamu.edu, www.qe.com.qa, www.qu.edu.qa, www.rohmuscat.org.om, www.sabic.com, www.sharjah.ac.ae, www.squ.edu.om, www.trade.gov, www.uaeu.ac.ae, www.unizwa.edu.om
- **TAX_NUMBER**: algadriapp.my.taker.io, alrajhi-capital.sa, amazingoman.net, assets.zoom.us, biga.my.taker.io, chickend.my.taker.io, eilek.my.taker.io, hsaa.s3.amazonaws.com, hyperbill.hyperpay.com, lahint.sa, magit.blob.core.windows.net, media.zid.store, rdc.dubailand.gov.ae, sa.inwani.com, scp.stc.com.bh, socpa.org.sa, solutions.com.sa, splonline.com.sa, store.tts.sa, thechefz.co, www.bank-abc.com, www.bankdhofar.com, www.centrallabuaq.ae, www.coursehero.com, www.dbr.sa, www.dpworld.com, www.etisalat.ae, www.lg.com, www.nbo.om, www.nfh.com.bh, www.oman-arabbank.com, www.pizzainnsaudi.com, www.pmu.edu.sa, www.scribd.com, x.com

## Documented ceilings — why some kinds are sparse / low-recall

- **COMMERCIAL_REGISTRATION** (92 spans): Witness/label-cued. Real CRs published in varied prose; un-cued mentions are not claimed (the curated set pins the label paths at 1.0).
- **NATIONAL_ID** (22 spans): Label-cued + bare-digit. Values are PUBLISHED VALIDATOR TEST-VECTORS (saudi-id-validator, django-localflavor test_kw/ae/qa, gov design-system format examples) — never a real individual's ID. Most appear in code/doc contexts with no detector witness, so regex recall is low by design.
- **PHONE** (204 spans): Bare 8-digit GCC locals are deliberately unmatched (no country code / leading 0), which dominates the miss set on diverse real pages.
